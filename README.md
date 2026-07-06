# damoLoad

Tools for generating controlled memory access workloads and comparing them against what [DAMON](https://docs.kernel.org/mm/damon/index.html) actually observes. Useful for understanding DAMON's sampling behavior, detection limits, and region adaptation.

---

## Repository Layout

```
damoLoad/
├── run_memtest.sh   — automated end-to-end runner (build → DAMON → compare)
├── compare.py       — per-region GT vs DAMON ASCII heatmap renderer
├── memtest/         — structured workload generator with ground truth logging
│   ├── README.md
│   ├── Makefile
│   ├── src/         — C sources
│   ├── configs/     — 80+ pre-made JSON workloads
│   └── scripts/     — config generators
└── hammer/          — minimal single-file load generator for quick experiments
    ├── hammer.c
    └── README.md
```

---

## Quick Start

Requires: Linux with DAMON (`CONFIG_DAMON=y`), `damo` installed, GCC, Python 3.

```bash
# clone
git clone https://github.com/daniellysy566/damoLoad.git
cd damoLoad

# run a workload (builds memtest, records with DAMON, shows heatmap)
sudo bash run_memtest.sh memtest/configs/11_sine_slow.json

# 100-region stress test
sudo bash run_memtest.sh memtest/configs/51_100reg_uniform_const.json
```

Results are saved to `memtest/results/`.

---

## Components

### `memtest/` — Structured Workload Generator

Runs configurable access patterns (sine, square, Zipf, hotspot, …) across multiple memory regions, logs every access with nanosecond timestamps (ground truth), then compares against DAMON's output.

See [memtest/README.md](memtest/README.md) for the full JSON workload format.

### `hammer/` — Quick Load Generator

Single C file. Hammers one region at a fixed Hz and prints its PID + address for immediate use with `damo record`.

See [hammer/README.md](hammer/README.md).

### `compare.py` — Heatmap Renderer

Called automatically by `run_memtest.sh`. For each region, calls `damo report heatmap --address_range` to scope the DAMON data, then renders GT and DAMON side by side:

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

---

## Key Findings

- **DAMON samples 1 random page per region per 5ms** — observed Hz ≈ real Hz × (pages_in_region)⁻¹ for uniform patterns
- **100-region configs**: DAMON requires regions sorted by ascending start address; `run_memtest.sh` handles this automatically
- **bounding-box problem**: avoid a single DAMON region spanning 100 separate mmaps — use per-region `-r` flags instead (done automatically)
- **`--address_range`** in `damo report heatmap` scopes each per-region heatmap correctly even when addresses are far apart
