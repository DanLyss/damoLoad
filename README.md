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

## `run_memtest.sh` — What It Does

This is the main entry point. You give it a config JSON, it does everything automatically:

```bash
sudo bash run_memtest.sh [config.json] [gt.log] [damon.data]
```

**Step by step:**

1. **Prints the config** — duration, regions, tracks, heatmap resolution
2. **Builds `memtest`** via `make` (incremental)
3. **Starts `memtest --auto config.json gt.log`** — the process mmaps all regions, prefaults all pages, then waits for `SIGUSR1` before starting accesses
4. **Parses the printed region addresses** from memtest's stdout — gets the exact virtual address ranges that were mmap'd
5. **Builds DAMON config** — uses `damo args damon` for the first region to get the correct JSON schema, then patches in all N regions sorted by ascending address. Sorting is required by the DAMON kernel interface.
6. **Starts `damo record`** — records DAMON observations to a `.data` file
7. **Sends `SIGUSR1`** to memtest — workload begins
8. **Waits** for both memtest and damo to finish
9. **Runs `compare.py`** — for each region, calls `damo report heatmap --address_range START END` scoped to that region, renders GT and DAMON side by side as ASCII heatmaps
10. **Saves result** to `memtest/results/<config_name>_<time>.txt`

**Why `--auto` mode?** Without it, you'd have to manually read the PID and region addresses from memtest's output, configure DAMON, and signal the process yourself. `--auto` mode makes memtest print machine-readable markers (`# PID=`, `# REGION`, `# READY`) so `run_memtest.sh` can parse them and automate everything.

**Why `fvaddr` ops?** `fvaddr` (fixed virtual address) is DAMON's mode for monitoring specific virtual address ranges of a process. Unlike `vaddr` mode (which adapts region boundaries), `fvaddr` keeps the regions exactly where we specify — matching the mmap'd regions in memtest. This is critical for comparing against ground truth.

**Why sort regions?** The DAMON kernel sysfs interface rejects configurations where regions are not in ascending order of start address — it returns `EINVAL`. memtest prints regions in allocation order (often descending), so `run_memtest.sh` sorts them before passing to DAMON.

## `compare.py` — Per-Region Heatmaps

Called automatically by `run_memtest.sh`, but can be run standalone:

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

  GT   — what memtest actually did
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
