#!/bin/bash
# run_nr_regions_sweep.sh — run the realistic-scale workload once per sweep
# point (min_nr_regions/max_nr_regions), each with its own single-kdamond
# damo record, and render a PNG chart comparing each config's total
# accesses/sec over time against ground truth.
#
# Why sequential, one kdamond at a time: damo record's default (tracer-based)
# recording merges multiple simultaneous kdamonds into one undifferentiated
# record (kdamond_idx=None) — confirmed empirically — and its --snapshot
# mode (which does tag kdamond_idx correctly) fails when combined with
# freshly-turned-on kdamonds. Running one real kdamond at a time, using the
# same proven single-kdamond recording path as run_memtest.sh, sidesteps
# both issues. The workload config is deterministic (fixed random seed), so
# the ground truth shape is the same across runs modulo real thread
# scheduling jitter.
#
# Usage:
#   export DAMON_DIR=/path/to/damo   # directory containing the damo executable
#   sudo -E bash memtest/scripts/run_nr_regions_sweep.sh [workload.json]
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)

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

WORKLOAD=${1:-"$REPO_DIR/memtest/configs/101_5500reg_realistic_app.json"}
MEMTEST_DIR="$REPO_DIR/memtest"
REPORT_PY="$SCRIPT_DIR/nr_regions_sweep_report.py"
RUN_TAG=$(date +%H%M%S)
WORK_DIR="/tmp/nr_sweep_${RUN_TAG}"
mkdir -p "$WORK_DIR"

SWEEP_MINS=(100 500 1000 2000 5000)

echo "==> Building memtest..."
make -C "$MEMTEST_DIR" -s || { echo "Build failed"; exit 1; }

if [ ! -f "$WORKLOAD" ]; then
    echo "==> Workload config not found, generating it..."
    python3 "$SCRIPT_DIR/gen_config_nr_regions_sweep.py" || { echo "Config generation failed"; exit 1; }
fi

DURATION=$(python3 -c "
import json
try:
    d = json.load(open('$WORKLOAD'))
    print(int(d.get('duration_sec', 60)) + 10)
except:
    print(70)
")
WORKLOAD_DUR=$(python3 -c "import json; d=json.load(open('$WORKLOAD')); print(int(d.get('duration_sec',60)))")

DATA_FILES=()
GT_FILES=()

for idx in "${!SWEEP_MINS[@]}"; do
    MIN_R=${SWEEP_MINS[$idx]}
    MAX_R=$((MIN_R * 5))
    GT_OUT="$WORK_DIR/gt_${MIN_R}.log"
    DAMON_OUT="$WORK_DIR/damon_${MIN_R}.data"
    MEMTEST_LOG="$WORK_DIR/memtest_${MIN_R}.log"

    echo ""
    echo "==> [$((idx+1))/${#SWEEP_MINS[@]}] min_nr_regions=$MIN_R max_nr_regions=$MAX_R"

    echo off > /sys/kernel/mm/damon/admin/kdamonds/0/state 2>/dev/null || true
    sleep 0.3

    echo "    Starting memtest..."
    rm -f "$MEMTEST_LOG" "$GT_OUT"
    "$MEMTEST_DIR/build/memtest" --auto "$WORKLOAD" "$GT_OUT" > "$MEMTEST_LOG" 2>&1 &
    MEMTEST_BGPID=$!
    for i in $(seq 1 300); do
        grep -q "^# READY" "$MEMTEST_LOG" 2>/dev/null && break
        sleep 0.2
        if ! kill -0 "$MEMTEST_BGPID" 2>/dev/null; then
            echo "ERROR: memtest exited early. Output:"
            tail -40 "$MEMTEST_LOG"
            exit 1
        fi
    done
    if ! grep -q "^# READY" "$MEMTEST_LOG" 2>/dev/null; then
        echo "ERROR: memtest did not become ready. Output:"
        tail -40 "$MEMTEST_LOG"
        exit 1
    fi
    APP_PID=$(grep "^# PID=" "$MEMTEST_LOG" | head -1 | cut -d= -f2)
    echo "    App PID: $APP_PID"

    REGIONS_TMP=$(mktemp)
    grep "^# REGION" "$MEMTEST_LOG" | python3 -c "
import sys
for line in sys.stdin:
    _, _, idx, start, end = line.split()
    print(f'{int(start, 16)}:{int(end, 16)}')
" > "$REGIONS_TMP"
    N_REGIONS=$(wc -l < "$REGIONS_TMP")
    if [ "$N_REGIONS" -eq 0 ]; then
        echo "ERROR: no regions parsed from memtest output:"
        tail -40 "$MEMTEST_LOG"
        kill "$APP_PID" 2>/dev/null
        exit 1
    fi
    echo "    Parsed $N_REGIONS regions"

    KFILE=$(mktemp)
    python3 "$SCRIPT_DIR/build_kdamonds_sweep.py" "$APP_PID" "$REGIONS_TMP" "$DAMO" "$MIN_R" "$MAX_R" > "$KFILE"
    rm -f "$REGIONS_TMP"
    if [ ! -s "$KFILE" ] || ! python3 -c "import json; json.load(open('$KFILE'))" 2>/dev/null; then
        echo "ERROR: failed to build kdamonds JSON:"
        cat "$KFILE"
        rm -f "$KFILE"
        kill "$APP_PID" 2>/dev/null
        exit 1
    fi

    rm -f "$DAMON_OUT"
    "$DAMO" record --kdamonds "$KFILE" --timeout "$DURATION" -o "$DAMON_OUT" &
    DAMO_PID=$!
    sleep 0.5

    echo "    Starting workload..."
    kill -USR1 "$APP_PID" || { echo "ERROR: could not signal memtest (pid $APP_PID)"; exit 1; }

    wait "$MEMTEST_BGPID" 2>/dev/null || true
    wait "$DAMO_PID"      2>/dev/null || true
    rm -f "$KFILE"

    if [ ! -f "$DAMON_OUT" ]; then
        echo "ERROR: $DAMON_OUT was not created"
        exit 1
    fi

    DATA_FILES+=("$DAMON_OUT")
    GT_FILES+=("$GT_OUT")
    echo "    Done: $(grep -c '' "$GT_OUT" 2>/dev/null) GT lines, recorded to $DAMON_OUT"
done

echo ""
echo "==> Building sweep report..."
RESULTS_DIR="$MEMTEST_DIR/results"
mkdir -p "$RESULTS_DIR"
PNG_OUT="$RESULTS_DIR/$(basename "$WORKLOAD" .json)_nr_regions_sweep_${RUN_TAG}.png"
python3 "$REPORT_PY" "$PNG_OUT" \
    --sweep "${SWEEP_MINS[@]}" \
    --data "${DATA_FILES[@]}" \
    --gt "${GT_FILES[@]}"
echo ""
echo "==> Chart saved: $PNG_OUT"
