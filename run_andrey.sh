#!/bin/bash
# run_andrey.sh — build andrey_hammer, drive it from a compressed passport,
# record with DAMON in parallel, compare against the live ground truth.
#
# Instead of a hand-written workload config, the access pattern comes from
# Andrey's compressed statistical model (code3.json passport + meta.json
# geometry) -- see ANDREY_PIPELINE.md for the full pipeline and file formats.
#
# Usage:
#   export DAMON_DIR=/path/to/damo   # directory containing the damo executable
#   sudo -E bash run_andrey.sh [passport.json] [meta.json] [gt.log] [damon.data] [original.io.txt] [extra andrey_hammer args...]
#
# original.io.txt (optional, default: sim_raw3.txt if present) is Andrey's
# own io-format text -- the reference this run's live DAMON recording gets
# compared against at the end via compare_io.py, once both sides are in the
# same io-format text shape (see "materialize io-format" step below).

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
META=${2:-"$SCRIPT_DIR/meta3.json"}
GT_OUT=${3:-/tmp/andrey_gt.log}
DAMON_OUT=${4:-/root/andrey_damon.data}
ORIGINAL_IO=${5:-"$SCRIPT_DIR/sim_raw3.txt"}
shift $(( $# < 5 ? $# : 5 )) 2>/dev/null
EXTRA_ARGS=("$@")

ANDREY_DIR="$SCRIPT_DIR/andrey_hammer"
COMPARE_PY="$SCRIPT_DIR/compare.py"
COMPARE_IO_PY="$SCRIPT_DIR/compare_io.py"
ANDREY_LOG=/tmp/andrey_hammer_out.txt
DAMON_IO_OUT="${DAMON_OUT%.data}.io.txt"

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
{ [ -e /sys/kernel/mm/damon/admin/kdamonds/0/state ] && echo off > /sys/kernel/mm/damon/admin/kdamonds/0/state; } 2>/dev/null || true
sleep 0.3

# How long to record: read steps/frame_dt straight out of andrey_hammer's own
# startup line rather than re-parsing the JSON in shell.
#
# This needs a BIG safety margin, not just a few seconds: andrey_hammer's
# pacing loop has a known drift bug (see ANDREY_PIPELINE.md "Known issues")
# where real per-frame duration runs well over the nominal frame_dt_ms --
# measured 24-38% over across different runs, and it varies run to run, not
# a fixed constant. If `damo record --timeout` is sized off the NOMINAL
# duration, it can expire and stop recording before andrey_hammer actually
# finishes -- which silently truncates the DAMON recording, missing however
# much of the run happens after the timeout. That's exactly what happened
# once: a 254-step run took 35.3s of real wall time against a nominal
# ~25.5s, but --timeout was set to ~30.5s (nominal + 5s), so DAMON's
# recording stopped ~5.7s (~40 frames) before andrey_hammer actually did.
# 2x nominal + 15s flat is deliberately generous until the drift itself is
# fixed (a debt-based pacing loop, see ANDREY_PIPELINE.md) rather than
# tuned tight to whatever the last observed overrun happened to be.
GEOM_LINE=$(grep "^Geometry:" "$ANDREY_LOG")
STEPS=$(echo "$GEOM_LINE" | grep -oP 'steps=\K[0-9]+')
FRAME_MS=$(echo "$GEOM_LINE" | grep -oP 'frame=\K[0-9.]+')
DURATION=$(python3 -c "print(int(($STEPS * $FRAME_MS) / 1000.0 * 2) + 15)" 2>/dev/null || echo 60)
echo "    Recording for ${DURATION}s (2x nominal + 15s margin for andrey_hammer's pacing drift)"

KDAMONDS=$(python3 "$SCRIPT_DIR/scripts/build_kdamonds.py" "$APP_PID" "$REGIONS_TMP" "$DAMO")
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
# compare.py's later positional args (damon_base/damon_max/damo_exe) only
# land correctly if time_rows/space_cols are BOTH present -- an empty RESOL
# here would shift DAMON_MIN into the time_rows slot and crash compare.py's
# int() parsing, so always pass real values instead of leaving it optional.
SPACE_COLS=$(python3 -c "import json; print(json.load(open('$META'))['matrix_geometry']['cols'])" 2>/dev/null || echo 20)
RESOL="$STEPS $SPACE_COLS"
python3 "$COMPARE_PY" "$DAMON_OUT" "$GT_OUT" $RESOL "$DAMON_MIN" "$DAMON_MAX" "$DAMO" | tee >(sed 's/\x1b\[[0-9;]*m//g' > "$LOG_FILE")
echo ""
echo "==> Log saved: $LOG_FILE"

# ── 7. materialize io-format ─────────────────────────────────────────────────
# Both sides of the pipeline should end at the same artifact shape (per the
# original spec: "damon file = damon.data = io format"). This turns what
# DAMON actually recorded into the same io-format text Andrey's Python model
# produces, as a real, inspectable file -- not just an implicit conversion
# hidden inside compare_io.py.
echo ""
echo "==> Materializing io-format from DAMON's recording..."
"$DAMO" report access --input "$DAMON_OUT" --raw_form > "$DAMON_IO_OUT"
echo "    $DAMON_IO_OUT"

# ── 8. compare two io-format files ──────────────────────────────────────────
if [ -f "$ORIGINAL_IO" ]; then
    echo ""
    echo "==> Comparing io-format vs io-format (original vs this run)..."
    python3 "$COMPARE_IO_PY" "$ORIGINAL_IO" "$DAMON_IO_OUT" --damo "$DAMO" \
        | tee >(sed 's/\x1b\[[0-9;]*m//g' > "${LOG_FILE%.txt}_io.txt")
    echo ""
    echo "==> Log saved: ${LOG_FILE%.txt}_io.txt"
else
    echo ""
    echo "==> Skipping comparisons against the original: '$ORIGINAL_IO' not found."
    echo "    Pass it explicitly: run_andrey.sh $PASSPORT $META $GT_OUT $DAMON_OUT path/to/original.io.txt"
fi

# ── 9. materialize io-format from gt.log directly (no DAMON) ────────────────
# Isolates replay fidelity from DAMON's own 5ms/200Hz sampling noise -- see
# ANDREY_PIPELINE.md's "Three different comparisons" table.
GT_IO_OUT="${GT_OUT%.log}.io.txt"
if [ -f "${GT_OUT}.frames" ]; then
    echo ""
    echo "==> Materializing io-format from gt.log directly (no DAMON)..."
    python3 "$ANDREY_DIR/gt_to_io.py" --gt "$GT_OUT" --frames "${GT_OUT}.frames" --meta "$META" --output "$GT_IO_OUT"

    if [ -f "$ORIGINAL_IO" ]; then
        echo ""
        echo "==> Comparing io-format vs io-format (original vs gt.log, no DAMON)..."
        python3 "$COMPARE_IO_PY" "$ORIGINAL_IO" "$GT_IO_OUT" \
            | tee >(sed 's/\x1b\[[0-9;]*m//g' > "${LOG_FILE%.txt}_io_gt.txt")
        echo "==> Log saved: ${LOG_FILE%.txt}_io_gt.txt"
    fi

    echo ""
    echo "==> Comparing io-format vs io-format (DAMON's observation vs gt.log, no original) ..."
    python3 "$COMPARE_IO_PY" "$GT_IO_OUT" "$DAMON_IO_OUT" \
        | tee >(sed 's/\x1b\[[0-9;]*m//g' > "${LOG_FILE%.txt}_io_damon_vs_gt.txt")
    echo "==> Log saved: ${LOG_FILE%.txt}_io_damon_vs_gt.txt"
else
    echo "==> Skipping gt.log-based io-format (no ${GT_OUT}.frames found)."
fi
