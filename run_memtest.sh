#!/bin/bash
# run_memtest.sh — build, run, record with DAMON, compare
#
# Usage:
#   export DAMON_DIR=/path/to/damo   # directory containing the damo executable
#   sudo -E bash run_memtest.sh [workload.json] [gt.log] [damon.data]

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if [ -z "$DAMON_DIR" ]; then
    echo "ERROR: DAMON_DIR is not set."
    echo "  Set it to the directory containing the damo executable, e.g.:"
    echo "    export DAMON_DIR=/usr/local/bin        # pip install damo"
    echo "    export DAMON_DIR=~/damo                # git checkout"
    exit 1
fi
DAMO="$DAMON_DIR/damo"
if [ ! -x "$DAMO" ]; then
    echo "ERROR: damo not found or not executable at $DAMO"
    exit 1
fi

WORKLOAD=${1:-"$SCRIPT_DIR/memtest/example.json"}
GT_OUT=${2:-/tmp/gt.log}
DAMON_OUT=${3:-/root/damon_test.data}
MEMTEST_DIR="$SCRIPT_DIR/memtest"
COMPARE_PY="$SCRIPT_DIR/compare.py"
MEMTEST_LOG=/tmp/memtest_out.txt

# ── 0. print config ───────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "  Workload: $(basename "$WORKLOAD")"
echo "──────────────────────────────────────────────────────"
python3 "$SCRIPT_DIR/memtest/scripts/print_config.py" "$WORKLOAD"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. build ──────────────────────────────────────────────────────────────────
echo "==> Building memtest..."
make -C "$MEMTEST_DIR" -s || { echo "Build failed"; exit 1; }

# ── 2. start memtest in --auto mode ──────────────────────────────────────────
echo "==> Starting memtest (workload: $WORKLOAD)..."
rm -f "$MEMTEST_LOG" "$GT_OUT"
"$MEMTEST_DIR/build/memtest" --auto "$WORKLOAD" "$GT_OUT" > "$MEMTEST_LOG" 2>&1 &
MEMTEST_BGPID=$!

echo "    Waiting for memtest to initialize..."
for i in $(seq 1 100); do
    grep -q "^# READY" "$MEMTEST_LOG" 2>/dev/null && break
    sleep 0.1
    if ! kill -0 "$MEMTEST_BGPID" 2>/dev/null; then
        echo "ERROR: memtest exited early. Output:"
        cat "$MEMTEST_LOG"
        exit 1
    fi
done

if ! grep -q "^# READY" "$MEMTEST_LOG" 2>/dev/null; then
    echo "ERROR: memtest did not become ready. Output:"
    cat "$MEMTEST_LOG"
    exit 1
fi

APP_PID=$(grep "^# PID=" "$MEMTEST_LOG" | head -1 | cut -d= -f2)
echo "    App PID: $APP_PID"

# parse regions → temp file (one DEC_START:DEC_END per line) + bounding box
REGIONS_TMP=$(mktemp)
DAMON_MIN=""
DAMON_MAX=""
while IFS= read -r line; do
    HEX_START=$(echo "$line" | awk '{print $4}')
    HEX_END=$(echo "$line"   | awk '{print $5}')
    DEC_START=$(printf '%d' "$HEX_START")
    DEC_END=$(printf '%d' "$HEX_END")
    if [ -z "$DAMON_MIN" ] || [ "$DEC_START" -lt "$DAMON_MIN" ]; then DAMON_MIN=$DEC_START; fi
    if [ -z "$DAMON_MAX" ] || [ "$DEC_END"   -gt "$DAMON_MAX" ]; then DAMON_MAX=$DEC_END;   fi
    echo "${DEC_START}:${DEC_END}" >> "$REGIONS_TMP"
    echo "    Region: ${HEX_START}-${HEX_END}  (dec: ${DEC_START}-${DEC_END})"
done < <(grep "^# REGION" "$MEMTEST_LOG")

if [ -z "$DAMON_MIN" ]; then
    echo "ERROR: no regions parsed from memtest output:"
    cat "$MEMTEST_LOG"
    exit 1
fi
echo "    DAMON bounding box: ${DAMON_MIN}-${DAMON_MAX}"

# ── 3. set up DAMON ──────────────────────────────────────────────────────────
echo "==> Setting up DAMON..."
echo off > /sys/kernel/mm/damon/admin/kdamonds/0/state 2>/dev/null || true
sleep 0.3

DURATION=$(python3 -c "
import json
try:
    d = json.load(open('$WORKLOAD'))
    print(int(d.get('duration_sec', 10)) + 5)
except:
    print(15)
")
echo "    Recording for ${DURATION}s"

KDAMONDS=$(python3 "$SCRIPT_DIR/memtest/scripts/build_kdamonds.py" "$APP_PID" "$REGIONS_TMP" "$DAMO")
rm -f "$REGIONS_TMP"

if [ -z "$KDAMONDS" ] || ! echo "$KDAMONDS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "ERROR: failed to build kdamonds JSON:"
    echo "$KDAMONDS"
    kill "$MEMTEST_BGPID" 2>/dev/null
    exit 1
fi
echo "    kdamonds: 1 target, $(grep -c '^# REGION' "$MEMTEST_LOG") regions"

rm -f "$DAMON_OUT"
"$DAMO" record --kdamonds "$KDAMONDS" --timeout "$DURATION" -o "$DAMON_OUT" &
DAMO_PID=$!
sleep 0.5

# ── 4. fire! ─────────────────────────────────────────────────────────────────
echo "==> Starting workload..."
kill -USR1 "$APP_PID" || { echo "ERROR: could not signal memtest (pid $APP_PID)"; exit 1; }

# ── 5. wait ───────────────────────────────────────────────────────────────────
WORKLOAD_DUR=$(python3 -c "import json; d=json.load(open('$WORKLOAD')); print(int(d.get('duration_sec',10)))")
echo "==> Workload: ${WORKLOAD_DUR}s  |  DAMON recording: ${DURATION}s (includes margin)"
wait "$MEMTEST_BGPID" 2>/dev/null || true
wait "$DAMO_PID"      2>/dev/null || true

echo ""
echo "==> memtest output:"
grep -v "^#" "$MEMTEST_LOG"

# ── 6. compare ───────────────────────────────────────────────────────────────
echo ""
echo "==> Comparing with DAMON..."
RESOL=$(python3 -c "
import json
try:
    d = json.load(open('$WORKLOAD'))
    t = d.get('heatmap_time_rows', '')
    s = d.get('heatmap_space_cols', '')
    if t and s:
        print(t, s)
except:
    pass
")
LOGS_DIR="$MEMTEST_DIR/results"
mkdir -p "$LOGS_DIR"
LOG_FILE="$LOGS_DIR/$(basename "$WORKLOAD" .json)_$(date +%H%M%S).txt"
python3 "$COMPARE_PY" "$DAMON_OUT" "$GT_OUT" $RESOL "$DAMON_MIN" "$DAMON_MAX" "$DAMO" | tee >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")
echo ""
echo "==> Log saved: $LOG_FILE"
