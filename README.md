# damoLoad

Tools for generating controlled memory access workloads and comparing them against what [DAMON](https://docs.kernel.org/mm/damon/index.html) actually observes.

Useful for:
- understanding DAMON's sampling behavior and detection limits
- validating kernel patches that change DAMON's monitoring accuracy
- reproducing specific access patterns and checking what the kernel sees

---

## Repository Layout

```
damoLoad/
├── run_memtest.sh   — end-to-end runner: build → record → compare
├── compare.py       — per-region GT vs DAMON ASCII heatmap renderer
├── memtest/         — structured workload generator with ground truth logging
│   ├── README.md
│   ├── Makefile
│   ├── src/         — C sources
│   ├── configs/     — 100+ pre-made JSON workloads
│   └── scripts/     — config generators
└── hammer/          — minimal single-file load generator for quick experiments
    ├── hammer.c
    └── README.md
```

---

## Requirements

| Component | Version / Notes |
|-----------|----------------|
| Linux kernel | ≥ 6.8 with `CONFIG_DAMON=y`, `CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y` |
| damo | ≥ 3.3.0 (`pip install damo`) |
| GCC | any modern version |
| Python | ≥ 3.10 |

> **Note:** The authors run this on a custom WSL2 kernel (`6.18.x-microsoft-standard-WSL2+`) with additional DAMON patches not yet merged upstream. Some features or behavior may differ on stock kernels. See [Known Patch Dependencies](#known-patch-dependencies) below.

---

## Quick Start

```bash
# clone
git clone https://github.com/DanLyss/damoLoad.git
cd damoLoad

# run a workload (builds memtest, records with DAMON, shows heatmap)
sudo bash run_memtest.sh memtest/configs/11_sine_slow.json

# 100-region stress test
sudo bash run_memtest.sh memtest/configs/51_100reg_uniform_const.json
```

Results are saved to `memtest/results/`.

---

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
5. **Builds DAMON config** — uses `damo args damon` for the first region to get the correct JSON schema, then patches in all 100 (or N) regions sorted by ascending address. Sorting is required by the DAMON kernel interface.
6. **Starts `damo record`** — records DAMON observations to a `.data` file
7. **Sends `SIGUSR1`** to memtest — workload begins
8. **Waits** for both memtest and damo to finish
9. **Runs `compare.py`** — for each region, calls `damo report heatmap --address_range START END` scoped to that region, renders GT and DAMON side by side as ASCII heatmaps
10. **Saves result** to `memtest/results/<config_name>_<time>.txt`

**Why `--auto` mode?** Without it, you'd have to manually read the PID and region addresses from memtest's output, configure DAMON, and signal the process yourself. `--auto` mode makes memtest print machine-readable markers (`# PID=`, `# REGION`, `# READY`) so `run_memtest.sh` can parse them and automate everything.

**Why `fvaddr` ops?** `fvaddr` (fixed virtual address) is DAMON's mode for monitoring specific virtual address ranges of a process. Unlike `vaddr` mode (which adapts region boundaries), `fvaddr` keeps the regions exactly where we specify — matching the mmap'd regions in memtest. This is critical for comparing against ground truth.

**Why sort regions?** The DAMON kernel sysfs interface rejects configurations where regions are not in ascending order of start address — it returns `EINVAL`. memtest prints regions in allocation order (often descending), so `run_memtest.sh` sorts them before passing to DAMON.

---

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

---

## Components

### `memtest/` — Structured Workload Generator

Runs configurable access patterns across multiple memory regions, logs every access with nanosecond timestamps (ground truth), then compares against DAMON's output.

Patterns are described along two orthogonal axes:
- **Temporal** — *when* and *how often*: `const`, `sine`, `square`, `ramp`, `steps`
- **Spatial** — *which page*: `uniform`, `hotspot`, `zipf`, `gaussian`, `sequential`, `all`

See [memtest/README.md](memtest/README.md) for the full JSON workload format.

### `hammer/` — Quick Load Generator

Single C file. Hammers one region at a fixed Hz and prints its PID + address for immediate use with `damo record`. No config file needed.

See [hammer/README.md](hammer/README.md).

---

## Known Patch Dependencies

### `damo` userspace tool — critical fix required

**[damonitor/damo PR #55](https://github.com/damonitor/damo/pull/55)** — `damo_report_heatmap: fix age backfill causing inflated access frequency in full recordings` (merged 2026-07-02).

Without this fix, `damo report heatmap` inflates reported frequencies **2–3×** in continuous recordings. Root cause: `add_pixel_heat()` extends the observe window backwards using region age (useful for sparse single-snapshot recordings), but doesn't clip it against the previous snapshot — so in a full recording every snapshot double-counts time already accounted by the previous one.

**Effect:** a 200 Hz process was reported as 500–1400 Hz. The inflation factor is `(age_cycle_length + 1) / 2`.

**Fix:** clips the backfill in `add_pixel_heat()` the same way `pixels_idxs_range()` already does.

**How to get it:** install damo from git after 2026-07-02, or wait for the PyPI release that follows damo 3.3.0:
```bash
pip install git+https://github.com/damonitor/damo.git
```

### Linux kernel

Tested on `6.18.x-microsoft-standard-WSL2` with `CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y`. Should work on any kernel ≥ 6.8 with those options enabled. Local kernel patches (if any) will be documented here as they are identified.

---

## Key Findings About DAMON Behavior

- **DAMON samples 1 random page per region per 5ms** — for a uniform pattern over N pages, observed Hz ≈ real Hz (any-page) not real Hz (per-page)
- **100-region configs**: DAMON requires regions sorted by ascending start address — `run_memtest.sh` handles this automatically
- **Bounding-box trap**: a single DAMON region spanning 100 separate mmaps wastes 97%+ of samples on unmapped gaps → use per-region `-r` flags (done automatically)
- **`--address_range`** in `damo report heatmap` scopes each per-region heatmap to the correct VA range even when regions are far apart in address space
