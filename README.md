# damoLoad

Tools for generating controlled memory access workloads and comparing them against what [DAMON](https://docs.kernel.org/mm/damon/index.html) actually observes.

```
damoLoad/
├── run_memtest.sh   — full automated runner: build → record → compare
├── compare.py       — per-region GT vs DAMON ASCII heatmap renderer
├── memtest/         — structured workload generator with ground truth logging
│   └── scripts/
│       ├── gen_config_nr_regions_sweep.py — generates the ~5500-region sweep workload
│       ├── build_kdamonds_sweep.py        — kdamonds JSON builder for one nr_regions sweep point
│       ├── run_nr_regions_sweep.sh        — orchestrates the full min_nr_regions/max_nr_regions sweep
│       └── nr_regions_sweep_report.py     — computes and plots the 6-line sweep chart
└── hammer/          — minimal single-file load generator for quick experiments
```

## Quick Start

Requires Linux with DAMON (`CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y`), damo, GCC, Python ≥ 3.10.

```bash
git clone https://github.com/DanLyss/damoLoad.git && cd damoLoad
```

**Set `DAMON_DIR`** — path to the directory containing the `damo` executable (required):

```bash
# pip install damo  →  damo lands in /usr/local/bin
export DAMON_DIR=/usr/local/bin

# git checkout of damonitor/damo  →  damo is at the repo root
export DAMON_DIR=/path/to/damo
```

**Run a workload:**

```bash
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

**Regions are not `MAP_FIXED` by default.** `region_alloc()` (`memtest/src/region.c`) only adds `MAP_FIXED_NOREPLACE` when a config explicitly sets a region's `"address"` field — none of the 101 configs shipped in `memtest/configs/` do this, so every region in every existing config is a plain `mmap(NULL, ...)`, placed wherever the kernel's allocator puts it. In practice, consecutive anonymous mmaps tend to land packed tightly together (verified: 5497/5499 region boundaries touching with zero gap in one 5500-region run), but this is an allocator implementation detail, not a guarantee — expect occasional large gaps (one ~162 MB gap was observed in that same run) if something else gets mapped in between. Set `"address"` explicitly (memtest already supports it) if a test needs a guaranteed, controlled layout.

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

## `run_nr_regions_sweep.sh` — min_nr_regions/max_nr_regions Sensitivity Sweep

Tests how DAMON's `min_nr_regions`/`max_nr_regions` monitoring-attribute bounds affect the fidelity of its *aggregate* access-rate signal (total accesses/sec summed across every tracked region) against ground truth, at a scale closer to a real heavyweight application (~5500 memory regions) than the existing 100–300 region stress configs.

```bash
sudo -E bash memtest/scripts/run_nr_regions_sweep.sh [workload.json]
```

Default workload: `memtest/configs/101_5500reg_realistic_app.json` (generated by `gen_config_nr_regions_sweep.py` if missing) — 5500 regions with a realistic size distribution (skewed toward small 16–64 KB allocations, with a long tail up to 1 MB; run the generator to see the exact histogram it prints) and a hot/warm/cold access-rate split (5% / 20% / 75% of regions), all riding a shared 4-phase step envelope (15s each) so the aggregate signal has a visible, checkable shape.

**What it does:**

1. Builds `memtest`, generates the config if it's missing.
2. Runs the workload **5 times sequentially** — once per `min_nr_regions` sweep point (100, 500, 1000, 2000, 5000; `max_nr_regions` = 5× min each time), each with its own fresh memtest run and a single-kdamond `damo record`.
3. Runs `nr_regions_sweep_report.py`, which loads each run's ground truth and DAMON recording, computes total accesses/sec over time for both, and renders one PNG with 6 lines (5 DAMON configs + real ground truth) to `memtest/results/`.

**Why 5 sequential runs instead of 1 run with 5 simultaneous kdamonds?** DAMON's sysfs genuinely supports multiple concurrent kdamond contexts on the same target process, but `damo record`'s default (tracer-based) recording path silently merges all of them into one undifferentiated record — `kdamond_idx`/`context_idx` come back as `None`. Its `--snapshot` mode does tag records correctly but fails outright when combined with freshly-turned-on kdamonds. Running one real kdamond at a time — the same single-kdamond path `run_memtest.sh` already uses — sidesteps both problems. The workload config is deterministic, so the ground truth shape is consistent across runs modulo real thread-scheduling jitter.

**Metric caveats (found the hard way, worth knowing before trusting the chart):**

- The aggregate Hz is `sum(region.nr_accesses.in_hz(actual_snapshot_duration))` across all currently-tracked regions — deliberately **not** weighted by region size (the same size-weighting bug already fixed in the heatmap tool below: weighting by size estimates bandwidth, not access count, and inflates whenever a region's real hot spot is a small fraction of the region's size).
- It uses each snapshot's **actual** elapsed duration (`end_time − start_time`), not the nominal configured `aggr_us`. At ~5500 real regions, DAMON's own aggregation cycle can take 3–7× longer than the configured 100ms (measured up to ~693ms) — using the nominal value there inflates the estimate and produces a misleadingly monotonic-looking "improvement" with region count that isn't real.
- Even after both fixes, DAMON's aggregate estimate stays well below ground truth at this scale — DAMON's own per-cycle overhead across thousands of regions becomes the bottleneck, not the `min_nr_regions` budget. There's also an unexplained real rise in DAMON's reported activity 5–10s *before* some ground-truth phase transitions that's still under investigation — don't take the chart as a fully-understood result yet.

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
