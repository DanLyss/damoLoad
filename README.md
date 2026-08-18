# damoLoad

Real-time memory load simulator built from a compressed statistical model of
a recorded [DAMON](https://docs.kernel.org/mm/damon/index.html) access
trace — see [`ANDREY_PIPELINE.md`](ANDREY_PIPELINE.md) for the full pipeline,
status, exact file formats, and build/test commands.

```
damoLoad/ (branch: andrey_math)
│
├── 📄 Docs
│   ├── README.md               — this file: quick start + map
│   └── ANDREY_PIPELINE.md      — start here: pipeline diagram, status, exact
│                                  file formats, known issues, test commands
│
├── 🔢 Real input data (from the fitting step, confidential/external)
│   ├── code3.json               — 10-channel statistical "passport"
│   ├── meta3.json                — geometry matching code3.json
│   └── sim_raw3.txt               — reference io-format trace (Python model output)
│
├── 🐍 Andrey's pipeline (pure Python, offline, no real memory, no DAMON)
│   ├── generate.py (1).txt        — ⚠️ actually the single-pass Module 3+4+5
│   │                                 (misleading name — see ANDREY_PIPELINE.md)
│   ├── simulate.py.txt             — ⚠️ actually Module 3 only (misleading name)
│   ├── reconstruct_heatmap.py.txt   — Module 4
│   └── format_raw.py.txt             — Module 5
│
├── ⚙️ This repo's pipeline (C, real time, real memory, real DAMON)
│   └── andrey_hammer/
│       ├── src/andrey_hammer.c   — the C driver: computes the profile itself,
│       │                           per frame, and drives LIVE memory accesses
│       │                           on its own mmap'd region (not a pre-
│       │                           rendered file) — see damo_replay.md for why
│       ├── Makefile
│       ├── README.md              — design rationale for this tool specifically
│       ├── gt_to_io.py             — converts gt.log → io-format text directly,
│       │                             bypassing DAMON's own sampling entirely
│       └── PACING_DRIFT_ISSUE.md   — pacing-drift bug: investigation, root
│                                     cause, fix (now FIXED)
│
├── 🔍 Comparison & orchestration
│   ├── run_andrey.sh            — one command: build → live run → damo record
│   │                               → all 3 io-format comparisons → reports
│   ├── compare.py                — gt.log vs DAMON heatmap (reused dependency)
│   └── compare_io.py              — direct io-format-vs-io-format shape comparison
│
├── 🔧 Supporting
│   ├── scripts/build_kdamonds.py  — builds a kdamonds JSON config for damo
│   │                                 record from a PID + region list
│   └── patches/                    — required damo patches, see below
│
└── 📝 damo_replay.md            — investigation notes: why damo's own `replay`
                                    subcommand doesn't reproduce a real address
                                    space, and what this repo does differently
```

## Quick Start

Requires Linux with DAMON (`CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y`), damo, GCC, Python ≥ 3.10.

```bash
git clone --branch andrey_math https://github.com/DanLyss/damoLoad.git && cd damoLoad
export DAMON_DIR=/usr/local/bin   # or wherever damo lives, see ANDREY_PIPELINE.md
sudo -E bash run_andrey.sh
```

That builds `andrey_hammer`, drives a live memory-access replay of
`code3.json`+`meta3.json` in real time, records it with a live `damo
record`, and saves four reports under `andrey_hammer/results/`:
ground truth vs DAMON (`compare.py`), then three io-format-vs-io-format
comparisons via `compare_io.py` — original vs DAMON's observation,
original vs this run's own ground truth (no DAMON), and DAMON's
observation vs this run's own ground truth (isolates DAMON's sampling
noise from everything else; see ANDREY_PIPELINE.md's "Three different
comparisons" table for what each one actually answers). Full
details, known issues, and lower-level manual test commands are in
[`ANDREY_PIPELINE.md`](ANDREY_PIPELINE.md).

## `compare.py` — Per-Region Heatmaps

Called automatically by `run_andrey.sh`, but can be run standalone:

```bash
python3 compare.py damon.data gt.log [time_rows] [space_cols] [damon_base] [damon_max]
```

For each region it:
1. Builds a GT heatmap from the ground truth log (exact access timestamps + page indices)
2. Calls `damo report heatmap --resol T S --address_range START END --output raw` — lets damo do the binning, scoped to this region's VA range
3. Renders both side by side with a shared Hz scale

```
═══════════════════════════════════════════════════════
  Region 0  base=0x7f10…  10 pages  resol=20×10
═══════════════════════════════════════════════════════

  scale: 0=3.0 Hz  ...  9=26.2 Hz

  GT   — what actually happened
  2314521235
  4430342432
  ...

  DAMON — what kernel observed
  3222222433
  5331452661
  ...

    col     GT Hz   DAMON Hz  ratio  bar
  ──────────────────────────────────────────────────
     p0      10.8       13.8  1.28  ████████████████████
```

Time goes down (one row = duration/time_rows seconds). Space goes right (one col = region_size/space_cols).

## `compare_io.py` — io-format vs io-format

Compares two files already in (or converted to) DAMON's raw access-report
text format directly — no ground-truth log needed. See the docstring at the
top of the file, and [`ANDREY_PIPELINE.md`](ANDREY_PIPELINE.md)'s "Design
decisions" section for why this is a *shape* comparison (address-fraction
normalized) rather than a literal address diff.

## Required `damo` Patches

Two changes to `damo_report_heatmap.py` are needed beyond upstream damo 3.3.0:

**1. Age backfill clip** — [damonitor/damo PR #55](https://github.com/damonitor/damo/pull/55) *(merged 2026-07-02)*

Without this, `damo report heatmap` inflates reported Hz by 2–3× in continuous recordings. Each snapshot's observe window extends backward into time already counted by the previous snapshot.

**2. Remove space weighting from heat formula** *(local, not yet upstream)*

Changes `heat = heat_val * account_time * account_sz` → `heat = heat_val * account_time`, and pixel accumulation from `time_unit * addr_unit` weighted to `time_unit` only. Makes the heatmap report frequency (Hz) rather than Hz×bytes, so values are directly comparable to ground truth.

**Install patched damo:**
```bash
# PR #55 is merged; patch 2 must be applied manually
pip install git+https://github.com/damonitor/damo.git
# then apply the heat formula patch to damo_report_heatmap.py
```

The exact diff is in [patches/damo_report_heatmap.patch](patches/damo_report_heatmap.patch).

## Key DAMON Behaviors

- DAMON samples **1 random page per region per 5ms** — max observable rate = 200 Hz
- For uniform access over N pages: observed Hz per page ≈ real Hz / N (probability of sampling the right page)
- Regions must be sorted by ascending start address in the sysfs config (`EINVAL` otherwise)
- Short bursts shorter than `aggr_interval` (100ms) may be missed or blurred
