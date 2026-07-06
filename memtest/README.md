# memtest — Memory Access Pattern Testing Tool

A tool for generating precise, configurable memory access patterns and comparing them against what DAMON actually observes. Useful for understanding DAMON's sampling behavior, region split/merge dynamics, and detection limits.

---

## Table of Contents

- [Overview](#overview)
- [Directory Structure](#directory-structure)
- [Architecture](#architecture)
- [Building](#building)
- [Quick Start](#quick-start)
- [Workload JSON Format](#workload-json-format)
  - [Regions](#regions)
  - [Tracks](#tracks)
  - [Temporal Generators](#temporal-generators)
  - [Spatial Selectors](#spatial-selectors)
- [Ground Truth Log](#ground-truth-log)
- [Comparing with DAMON](#comparing-with-damon)
- [Understanding the Results](#understanding-the-results)
- [DAMON Detection Limits](#damon-detection-limits)

---

## Overview

DAMON is a Linux kernel subsystem that monitors memory access patterns. It works by sampling one random page per region every `sample_interval` (typically 5ms), accumulating counts over `aggr_interval` (typically 100ms), and adapting region boundaries via split/merge.

The problem: it's hard to know what DAMON actually *sees* vs what's *really happening*. memtest solves this by:

1. Running a precisely controlled access pattern
2. Logging every single access with nanosecond timestamps (ground truth)
3. Comparing ground truth against DAMON's output as side-by-side ASCII heatmaps

---

## Directory Structure

```
memtest/
├── Makefile
├── README.md
├── example.json        — minimal example workload
├── src/
│   ├── main.c
│   ├── region.{h,c}    — mmap allocation, optional fixed VA
│   ├── temporal.{h,c}  — frequency generators (const, sine, square, ramp, steps)
│   ├── spatial.{h,c}   — page selectors (uniform, hotspot, zipf, gaussian, sequential, all)
│   ├── gt_log.{h,c}    — ground truth ring buffer → file
│   ├── track.{h,c}     — one thread per spatial×temporal pattern
│   └── workload.{h,c}  — JSON loader, orchestration, GT flush
├── scripts/
│   ├── gen_configs.py       — generates configs 01–50
│   └── gen_configs_hard.py  — generates configs 51+ (100-region stress tests)
├── build/              — compiled output (created by make)
│   └── memtest
├── configs/            — 80+ pre-made workload JSON files
└── results/            — saved heatmap comparison logs
```

---

## Architecture

```
workload.json
      │
      ▼
  workload_t
  ├── region[0]  ─── mmap'd memory block (pages 0..N)
  ├── region[1]  ─── mmap'd memory block (pages 0..M)
  │
  ├── track[0]   ─── thread: spatial[0] × temporal[0] → region[0]
  ├── track[1]   ─── thread: spatial[1] × temporal[1] → region[1]
  └── track[2]   ─── thread: spatial[2] × temporal[2] → region[1]
        │
        ▼
    gt_log  ──────────────────────────────► gt.log
                                           (ts_ns region page)
```

**Regions** are independent `mmap` allocations — each lives at a different virtual address, so DAMON can monitor them separately. An optional `"address"` field pins the region to a specific virtual address via `MAP_FIXED_NOREPLACE`.

**Tracks** are threads. Each track has:
- a *spatial selector* — which page to access
- a *temporal generator* — how often to access it
- start/end times — when within the workload the track is active

Multiple tracks can target the same region simultaneously (additive).

**Timing** uses a debt-based loop: `debt_ns += elapsed; while (debt_ns >= interval_ns) { access(); debt_ns -= interval_ns; }`. This avoids drift and doesn't depend on sleep accuracy.

---

## Building

Requires: GCC, pthreads, libm. No external dependencies.

```bash
cd memtest
make
```

Produces `build/memtest`. To clean: `make clean`.

---

## Quick Start

The easiest way is the fully automated script (run from the repo root):

```bash
# run with example.json
sudo bash run_memtest.sh

# run a specific config
sudo bash run_memtest.sh memtest/configs/11_sine_slow.json
```

The script automatically:
1. Builds `memtest` via `make`
2. Starts `memtest --auto` and parses the printed PID and region addresses
3. Configures DAMON (`fvaddr` ops) with one target containing all regions, sorted by address
4. Starts `damo record`
5. Signals memtest to begin the workload
6. Waits for both to finish
7. Runs `compare.py` — shows per-region GT vs DAMON ASCII heatmaps
8. Saves a clean-text copy to `memtest/results/<name>_<time>.txt`

---

## Workload JSON Format

```json
{
  "duration_sec": 30,
  "heatmap_time_rows": 30,
  "heatmap_space_cols": 10,
  "regions": [ ... ],
  "tracks":  [ ... ]
}
```

| Field                | Type   | Description                                        |
|----------------------|--------|----------------------------------------------------|
| `duration_sec`       | number | Total workload duration in seconds                 |
| `heatmap_time_rows`  | int    | Heatmap rows (time axis); default = duration_sec   |
| `heatmap_space_cols` | int    | Heatmap columns (space axis); default = n_pages    |
| `regions`            | array  | Memory regions to allocate                         |
| `tracks`             | array  | Access pattern threads                             |

---

### Regions

Each region is an independent `mmap` allocation. Referenced by zero-based index from tracks.

```json
"regions": [
  {"pages": 10},
  {"pages": 40, "address": "0x7f1000000000"},
  {"pages": 5}
]
```

| Field     | Type   | Default | Description                                            |
|-----------|--------|---------|--------------------------------------------------------|
| `pages`   | int    | 10      | Region size in 4 KB pages                             |
| `address` | string | —       | Optional fixed virtual address (hex, e.g. `"0x7f10…"`). Uses `MAP_FIXED_NOREPLACE` — fails if the VA is already occupied. Omit to let the kernel choose. |

All pages are prefaulted on allocation so DAMON sees them immediately.

---

### Tracks

Each track is a thread that accesses one region following a spatial × temporal pattern.

```json
{
  "region":    0,
  "spatial":   { ... },
  "temporal":  { ... },
  "start_sec": 5.0,
  "end_sec":   20.0
}
```

| Field       | Type   | Default         | Description                            |
|-------------|--------|-----------------|----------------------------------------|
| `region`    | int    | 0               | Index into the `regions` array         |
| `spatial`   | object | —               | Page selection strategy                |
| `temporal`  | object | —               | Access frequency over time             |
| `start_sec` | number | 0               | When this track activates              |
| `end_sec`   | number | `duration_sec`  | When this track stops                  |

Multiple tracks can target the same region — their accesses are independent and additive.

---

### Temporal Generators

#### `const` — Constant frequency

```json
{"type": "const", "hz": 100}
```

#### `sine` — Sinusoidal frequency

```json
{"type": "sine", "base_hz": 100, "amplitude": 80, "period_sec": 2.0, "phase_rad": 0.0}
```

`hz(t) = base_hz + amplitude × sin(2π × t / period_sec + phase_rad)`, clamped to 0.

#### `square` — Square wave (burst/silence)

```json
{"type": "square", "on_hz": 200, "duty": 0.3, "period_sec": 1.0, "phase_rad": 0.0}
```

For `duty` fraction of each period: accesses at `on_hz`. Rest: silence.

#### `ramp` — Linear ramp

```json
{"type": "ramp", "start_hz": 0, "end_hz": 300}
```

#### `steps` — Step function

```json
{
  "type": "steps",
  "steps": [
    {"hz": 50,  "duration_sec": 10},
    {"hz": 200, "duration_sec": 5},
    {"hz": 10,  "duration_sec": 10}
  ]
}
```

---

### Spatial Selectors

| Type         | Description                                                   |
|--------------|---------------------------------------------------------------|
| `uniform`    | Each access picks a random page with equal probability        |
| `sequential` | Round-robin: 0, 1, 2, …, N-1, 0, 1, …                       |
| `hotspot`    | `hot_ratio` fraction of accesses to listed `hot_pages`        |
| `zipf`       | Page k gets probability ∝ 1/k^s (higher s → more skewed)     |
| `gaussian`   | Bell curve around `center` page with std dev `sigma` pages    |
| `all`        | Every tick touches **all** pages; each page gets full `hz`    |

```json
{"type": "hotspot", "hot_pages": [0, 1], "hot_ratio": 0.9}
{"type": "zipf",    "s": 1.5}
{"type": "gaussian","center": 5.0, "sigma": 1.5}
```

---

## Ground Truth Log

Written to the path passed on the command line. Format:

```
# region 0 base=0x7f1000000000 pages=10
# region 1 base=0x7f2000000000 pages=5
# ts_ns region page
1751500000000000 0 3
1751500000006666 0 1
1751500001234567 1 2
```

Log capacity: 10 million entries. Excess entries are silently dropped.

---

## Comparing with DAMON

`compare.py` (at repo root) displays per-region side-by-side ASCII heatmaps. For each region it calls `damo report heatmap --address_range START END` so DAMON's output is properly scoped to that region's VA range.

```
═══════════════════════════════════════════════════════
  Region 0  base=0x7f1000000000  10 pages  resol=15×10
═══════════════════════════════════════════════════════

  scale: 0=45.6 Hz  ...  9=135.0 Hz

  GT   — what memtest actually did
  9900000000
  9900000000
  ...

  DAMON — what kernel observed
  7800000000
  8700000000
  ...

    col     GT Hz   DAMON Hz  ratio  bar
  ──────────────────────────────────────────────────
     p0      121.5       98.2  0.81  ████████████████
     p1      121.5       42.1  0.35  ███████
```

Both heatmaps share the same scale. Time goes down, space goes right.

---

## Pre-made Configs

80+ workload configs are provided in `configs/`:

| Range  | What they test |
|--------|----------------|
| 01–10  | Single region, single track, basic temporals (const, ramp) |
| 11–20  | All temporal and spatial types individually |
| 21–35  | Combined spatial×temporal, multiple tracks, large regions |
| 36–50  | Multiple regions, phase-shifted tracks, burst detection, stress tests |
| 51–83  | 100-region stress tests: uniform, sine sweeps, square anti-phase, cascades, hotspot gradients, Zipf, Gaussian, burst visibility |

To regenerate:
```bash
python3 scripts/gen_configs.py        # configs 01–50
python3 scripts/gen_configs_hard.py   # configs 51+
```

---

## Understanding the Results

### What DAMON actually measures

DAMON picks **one random page** per region per `sample_interval` (5ms). It checks whether that page was accessed (hardware accessed bit). Over `aggr_interval` (100ms), it accumulates `nr_accesses`.

`hz = nr_accesses / aggr_interval_sec`

Maximum observable Hz = `1 / sample_interval = 200 Hz`.

### Why DAMON sees lower Hz than reality

With **uniform** spatial over N pages: P(sample hits accessed page) = 1/N → observed Hz ≈ real Hz / N.

With **hotspot** pages 0–1 (90% traffic) in 10-page region: P(sample hits hot page) ≈ 0.9×(2/10) + 0.1×(8/10)×0 ≈ 0.18+0.08 = ~0.28 → DAMON sees ~28% of real Hz.

### Why the sine wave looks blurred

DAMON averages over `aggr_interval` = 100ms. If `period_sec = 2.0`, each sample covers 1/20 of a cycle. Fast oscillations (period < 200ms) become nearly invisible.

### Why short bursts disappear

`square(on_hz=200, duty=0.05, period=1.0s)` → 50ms burst per second. If the burst straddles two `aggr_interval` windows, each window shows only half the burst energy.

---

## DAMON Detection Limits

| Scenario | Condition | DAMON sees |
|---|---|---|
| Low Hz, single page | `hz < 10` | Intermittent; may round to 0 |
| High Hz, many pages | `hz / n_pages < threshold` | 0 (merged into cold region) |
| Short burst | `burst_duration < aggr_interval` | Blurred or missed |
| Fast sine | `period < 2 × aggr_interval` | Nearly flat line |
| Hotspot before split | While DAMON hasn't adapted yet | Same low Hz as cold pages |
| Hotspot after split | Region split around hot pages | Correctly elevated Hz |
