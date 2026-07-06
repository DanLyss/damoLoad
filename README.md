# damoLoad

Tools for generating controlled memory access workloads and comparing them against what [DAMON](https://docs.kernel.org/mm/damon/index.html) actually observes.

```
damoLoad/
├── run_memtest.sh   — end-to-end runner: build → record → compare
├── compare.py       — per-region GT vs DAMON ASCII heatmap renderer
├── memtest/         — structured workload generator with ground truth logging
└── hammer/          — minimal single-file load generator for quick experiments
```

## Quick Start

Requires Linux with DAMON (`CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y`), damo, GCC, Python ≥ 3.10.

```bash
git clone https://github.com/DanLyss/damoLoad.git && cd damoLoad

# build, record with DAMON, compare — all automatic
sudo bash run_memtest.sh memtest/configs/11_sine_slow.json

# 100-region stress test
sudo bash run_memtest.sh memtest/configs/51_100reg_uniform_const.json
```

Results saved to `memtest/results/`. See [memtest/README.md](memtest/README.md) for the full config format.

## How `run_memtest.sh` Works

1. Builds `memtest` via `make`
2. Starts `memtest --auto config.json` — mmaps all regions, prefaults pages, waits for signal
3. Parses printed region addresses (`# REGION` markers from memtest stdout)
4. Builds DAMON config: one target with all regions sorted by ascending address (DAMON requires this)
5. Starts `damo record` with `fvaddr` ops (fixed virtual address — tracks exactly the mmapped ranges)
6. Sends `SIGUSR1` to memtest — workload begins
7. Waits for both to finish, runs `compare.py`, saves result

`compare.py` calls `damo report heatmap --address_range START END` per region so each 40 KB region gets its own correctly-scoped heatmap, not a pixel in a 167 MB bounding box.

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
