#!/bin/bash
# run_andrey.sh — build andrey_hammer, drive it from a compressed passport,
# record with DAMON in parallel, compare against the live ground truth.
#
# This is the "andrey_math" counterpart to run_memtest.sh: instead of a
# hand-written workload.json, the access pattern comes from Andrey's
# compressed statistical model (code3.json passport + meta.json geometry).
#
# Usage:
#   export DAMON_DIR=/path/to/damo   # directory containing the damo executable
#   sudo -E bash run_andrey.sh [passport.json] [meta.json] [gt.log] [damon.data] [extra andrey_hammer args...]

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

PASSPORT=${1:-"$SCRIPT_DIR/code3.json"}
META=${2:-"$SCRIPT_DIR/andrey_hammer/meta.example.json"}
GT_OUT=${3:-/tmp/andrey_gt.log}
DAMON_OUT=${4:-/root/andrey_damon.data}
shift $(( $# < 4 ? $# : 4 )) 2>/dev/null
EXTRA_ARGS=("$@")

ANDREY_DIR="$SCRIPT_DIR/andrey_hammer"
COMPARE_PY="$SCRIPT_DIR/compare.py"
ANDREY_LOG=/tmp/andrey_hammer_out.txt

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "  Passport: $(basename "$PASSPORT")"
echo "  Meta:     $(basename "$META")"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── 1. build ──────────────────────────────────────────────────────────────────
echo "==> Building andrey_hammer..."
make -C "$ANDREY_DIR" -s || { echo "Build failed"; exit 1; }

# ── 2. start andrey_hammer in --auto mode ────────────────────────────────────
echo "==> Starting andrey_hammer (passport: $PASSPORT, meta: $META)..."
rm -f "$ANDREY_LOG" "$GT_OUT"
"$ANDREY_DIR/build/andrey_hammer" --auto "$PASSPORT" "$META" "$GT_OUT" "${EXTRA_ARGS[@]}" > "$ANDREY_LOG" 2>&1 &
ANDREY_BGPID=$!

echo "    Waiting for andrey_hammer to initialize..."
for i in $(seq 1 100); do
    grep -q "^# READY" "$ANDREY_LOG" 2>/dev/null && break
    sleep 0.1
    if ! kill -0 "$ANDREY_BGPID" 2>/dev/null; then
        echo "ERROR: andrey_hammer exited early. Output:"
        cat "$ANDREY_LOG"
        exit 1
    fi
done

if ! grep -q "^# READY" "$ANDREY_LOG" 2>/dev/null; then
    echo "ERROR: andrey_hammer did not become ready. Output:"
    cat "$ANDREY_LOG"
    exit 1
fi

APP_PID=$(grep "^# PID=" "$ANDREY_LOG" | head -1 | cut -d= -f2)
echo "    App PID: $APP_PID"

REGIONS_TMP=$(mktemp)
DAMON_MIN=""
DAMON_MAX=""
while IFS= read -r line; do
    HEX_START=$(echo "$line" | awk '{print $4}')
    HEX_END=$(echo "$line"   | awk '{print $5}')
    DEC_START=$(printf '%d' "$HEX_START")
    DEC_END=$(printf '%d' "$HEX_END")
    DAMON_MIN=$DEC_START
    DAMON_MAX=$DEC_END
    echo "${DEC_START}:${DEC_END}" >> "$REGIONS_TMP"
    echo "    Region: ${HEX_START}-${HEX_END}  (dec: ${DEC_START}-${DEC_END})"
done < <(grep "^# REGION" "$ANDREY_LOG")

if [ -z "$DAMON_MIN" ]; then
    echo "ERROR: no region parsed from andrey_hammer output:"
    cat "$ANDREY_LOG"
    exit 1
fi

# ── 3. set up DAMON ──────────────────────────────────────────────────────────
echo "==> Setting up DAMON..."
echo off > /sys/kernel/mm/damon/admin/kdamonds/0/state 2>/dev/null || true
sleep 0.3

# how long to record: read steps/frame_dt straight out of andrey_hammer's own
# startup line rather than re-parsing the JSON in shell
GEOM_LINE=$(grep "^Geometry:" "$ANDREY_LOG")
STEPS=$(echo "$GEOM_LINE" | grep -oP 'steps=\K[0-9]+')
FRAME_MS=$(echo "$GEOM_LINE" | grep -oP 'frame=\K[0-9.]+')
DURATION=$(python3 -c "print(int(($STEPS * $FRAME_MS) / 1000.0) + 5)" 2>/dev/null || echo 30)
echo "    Recording for ${DURATION}s"

KDAMONDS=$(python3 "$SCRIPT_DIR/memtest/scripts/build_kdamonds.py" "$APP_PID" "$REGIONS_TMP" "$DAMO")
rm -f "$REGIONS_TMP"

if [ -z "$KDAMONDS" ] || ! echo "$KDAMONDS" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
    echo "ERROR: failed to build kdamonds JSON:"
    echo "$KDAMONDS"
    kill "$ANDREY_BGPID" 2>/dev/null
    exit 1
fi

rm -f "$DAMON_OUT"
"$DAMO" record --kdamonds "$KDAMONDS" --timeout "$DURATION" -o "$DAMON_OUT" &
DAMO_PID=$!
sleep 0.5

# ── 4. fire! ─────────────────────────────────────────────────────────────────
echo "==> Starting live simulation..."
kill -USR1 "$APP_PID" || { echo "ERROR: could not signal andrey_hammer (pid $APP_PID)"; exit 1; }

# ── 5. wait ───────────────────────────────────────────────────────────────────
wait "$ANDREY_BGPID" 2>/dev/null || true
wait "$DAMO_PID"      2>/dev/null || true

echo ""
echo "==> andrey_hammer output:"
grep -v "^#" "$ANDREY_LOG"

# ── 6. compare ───────────────────────────────────────────────────────────────
echo ""
echo "==> Comparing with DAMON..."
LOGS_DIR="$ANDREY_DIR/results"
mkdir -p "$LOGS_DIR"
LOG_FILE="$LOGS_DIR/$(basename "$PASSPORT" .json)_$(date +%H%M%S).txt"
# no heatmap_time_rows/space_cols override here (unlike run_memtest.sh, there's
# no workload.json to read them from) — let compare.py fall back to its own
# defaults (duration-derived rows, n_pages columns)
RESOL=""
python3 "$COMPARE_PY" "$DAMON_OUT" "$GT_OUT" $RESOL "$DAMON_MIN" "$DAMON_MAX" "$DAMO" | tee >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")
echo ""
echo "==> Log saved: $LOG_FILE"
