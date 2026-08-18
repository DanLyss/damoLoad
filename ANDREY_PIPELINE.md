# Andrey pipeline — status & handoff

This document exists so a new agent/dev can pick up this branch (`andrey_math`)
without re-deriving context from git history or chat logs. It covers: what
the pipeline is, what's built, what's validated, what's still missing, exact
file formats, and exact commands to build/run/test everything.

## The pipeline

```
                    ┌─────────────────────────────────────┐
                    │  CONFIDENTIAL — not in this repo,    │
                    │  not our concern to build             │
                    │                                       │
  real damon.data   │  fitting script (Python)              │
  (io format)  ─────┼─►  reduces a full trace down to a     │
                    │    small statistical "passport"       │
                    └───────────────────┬───────────────────┘
                                         ▼
                          code3.json (passport) + meta3.json (geometry)
                                         │
                                         ▼            ← THIS REPO starts here
                          ┌──────────────────────────┐
                          │  andrey_hammer (C)        │
                          │  computes the profile      │
                          │  itself, per frame, in     │
                          │  real time, and touches     │
                          │  real memory pages RIGHT     │
                          │  NOW — see andrey_hammer/  │
                          └──────────────┬─────────────┘
                                         │  (an independent `damo record`
                                         │   watches this process live)
                                         ▼
                              fresh damon.data (io format)
                                         │
                    original io-format ──┤
                    trace (input to the  │
                    confidential fitting)▼
                          ┌──────────────────────────┐
                          │  compare_io.py             │
                          │  shape comparison of the    │
                          │  two io-format traces        │
                          └──────────────┬─────────────┘
                                         ▼
                                   final report
```

`run_andrey.sh` wires the middle three boxes together automatically (build →
run andrey_hammer → `damo record` in parallel → compare).

## What's in this repo, file by file

| Path | What it is | Status |
|---|---|---|
| `code3.json` | Real passport (10-channel statistical model) — see format below | Given, real |
| `meta3.json` | Real geometry matching `code3.json` — confirmed: its address span (696320 B = 680 KiB) matches `sim_raw3.txt` exactly, so this is the geometry that produced it | Given, real |
| `sim_raw3.txt` | Real example output of the Python model on `code3.json`+`meta3.json` (io-format text, 254 snapshots) | Given, real — use as the shape reference |
| `damo_replay.md` | Investigation notes: why `damo replay` (damo's own built-in replay subcommand) does NOT reproduce a real address-space pattern — motivates `andrey_hammer`'s design | Given, real |
| `compare.py`, `run_memtest.sh`, `memtest/`, `hammer/` | Pre-existing ground-truth-vs-DAMON tooling, unrelated to the passport model except that `andrey_hammer` reuses `compare.py`'s gt.log format and `memtest/scripts/build_kdamonds.py` | Given, real, unchanged |
| **`andrey_hammer/`** | **New.** C port of the passport model that drives LIVE memory accesses in real time (not a pre-rendered file). See `andrey_hammer/README.md` for full design rationale | **Built, compiled. See "Known issues" below — NOT yet numerically validated** |
| **`run_andrey.sh`** | **New.** Automated build → run → `damo record` → compare orchestration, mirrors `run_memtest.sh` | **Built. NOT yet run end-to-end** (needs interactive `sudo` — see Testing) |
| **`compare_io.py`** | **New.** Direct io-format-vs-io-format shape comparison (Pearson r, cosine similarity, normalized RMSE, separate time/space-profile correlations, ASCII heatmap) | **Built, tested** against `sim_raw3.txt` and used for the C-vs-Python check below |

## ⚠️ Filename trap in the Python reference scripts

The two files `generate.py (1).txt` and `simulate.py.txt` are **named the
opposite of what they contain** — confirmed by actually running both, not
just reading docstrings casually:

| Filename on GitHub | What's actually inside |
|---|---|
| **`generate.py (1).txt`** | The **single-pass combined simulator** (Module 3+4+5 in one loop) — docstring says "Single-Pass Streaming Simulator... Unifies trajectory waveform synthesis (Module 3), Super-Gaussian spatial reconstruction (Module 4), and DAMON region formatting (Module 5-Raw)". CLI: `--passport --meta --output-raw-log --steps ...`. **This is the file to run for an end-to-end Python reference trace**, and the one `andrey_hammer.c`'s math was ported from. |
| **`simulate.py.txt`** | **Module 3 only** — docstring says "Symmetrical 10-Channel Parametric Waveform Simulator". CLI: `--passport --meta --output-traj --steps ...`. Writes a trajectory CSV, not an io-format log — needs `reconstruct_heatmap.py.txt` + `format_raw.py.txt` chained after it to get to text. |

`reconstruct_heatmap.py.txt` (Module 4) and `format_raw.py.txt` (Module
5-Raw) are named correctly — only these two are swapped. If re-fetching
these files from wherever the confidential pipeline lives, verify the
docstring before trusting the filename.

## What's missing

**The fitting step itself** (`io-format → code3.json` + `meta.json`) is
confidential and lives outside this repo. Not our job to build. Everything
else needed to test this branch is now present (both `code3.json` and
`meta3.json` are real).

## Known issues / open investigation

**C-vs-Python total-accesses mismatch, ~1.5x, appears systematic (not RNG
noise).** Ran `andrey_hammer` and the Python reference (`generate.py (1).txt`)
on the *same* `code3.json` + geometry, 100 steps, 5 different seeds each:

```
seed=1  python_total=14532   C_total=22783
seed=2  python_total=15649   C_total=22294
seed=3  python_total=14323   C_total=21749
seed=4  python_total=13912   C_total=22064
seed=5  python_total=15365   C_total=21908
```

Python: 13912–15649 (tight spread, ~12%). C: 21749–22783 (tight spread,
~5%). The *within-language* spread is small and the *between-language* gap
(~1.5x, consistently) is large — that pattern means a real formula
discrepancy somewhere in `andrey_hammer.c`'s `channel_precompute()` /
`channel_step()` vs the reference's per-channel precompute block (`generate.py
(1).txt` lines ~225–266 for constants, ~290–329 for the per-step update),
not bad luck. **Not yet root-caused — this was mid-investigation when
interrupted.** Whoever picks this up next: re-run the two commands below and
diff the precomputed constants (`p_k, p_b, p_sigma_x, phi_v, phi_z, alpha,
mu_eps, std_z, scale_factor, theo_fluct_std`) for one channel directly,
rather than comparing only the final output — that'll localize it faster
than comparing totals.

```bash
# Python reference
python3 "generate.py (1).txt" --passport code3.json --meta meta3.json \
    --output-raw-log /tmp/python_ref.io.txt --steps 100 --seed 1

# C
cd andrey_hammer && make
./build/andrey_hammer ../code3.json ../meta3.json /tmp/gt.log --steps 100 --seed 1 <<< ''
```

Separately, the C driver's real-time pacing loop shows **timing drift under
WSL2** (~25–30% frame overrun observed) — `andrey_hammer.c`'s per-frame
`sleep_ns(remaining_ns)` padding doesn't carry debt across frames the way
`memtest/src/track.c`'s debt-based loop does. Worth porting that pattern in
if wall-clock fidelity matters for the live DAMON test (Level 1 below isn't
affected in principle, since DAMON aggregates over its own window
regardless — but a `compare_io.py` time-profile check against nominal
frame boundaries will look worse than it should until this is fixed).

## Exact file formats `andrey_hammer` expects

### `meta.json` (real example: `meta3.json`)

```json
{
    "matrix_geometry": { "cols": 170, "rows": 254 },
    "physical_bounds": {
        "active_min_addr": "0x556c637ac000",
        "active_max_addr": "0x556c63856000"
    },
    "time_bounds_ms": { "start_ms": 0, "end_ms": 25517 },
    "super_gaussian_p": 2.0
}
```

| Key | Required? | Meaning |
|---|---|---|
| `super_gaussian_p` | **yes** | shape parameter of the spatial mixture |
| `matrix_geometry.cols` | **yes** | number of spatial bins |
| `matrix_geometry.rows` | **yes** | number of time frames the passport was fit over |
| `time_bounds_ms.{start_ms,end_ms}` | **yes** (or `time_bounds_us.{start_us,end_us}`) | `frame_dt_ms = (end_ms-start_ms)/rows` |
| `physical_bounds.{active_min_addr,active_max_addr}` | **yes** (or top-level `start_addr`/`end_addr`) | hex string or number; **only the span `end-start` is used** — `andrey_hammer` mmaps its own region of that size, it does NOT reuse these as literal addresses (see `andrey_hammer/README.md` for why) |
| `base_time_absolute` | no | cosmetic, log header only |

Extra keys (`physical_bounds.span_bytes`, `bin_size_bytes`, top-level
`time_step_ratio` — all present in `meta3.json`) are harmless; `andrey_hammer`
ignores unknown keys.

### `code3.json`

10 required top-level keys: `w1, mu1, sigma1, w2, mu2, sigma2, w3, mu3, sigma3, M_raw`. Each is an object with:

| Field | Required? | Default |
|---|---|---|
| `trend_slope`, `trend_intercept`, `std_dev`, `skewness`, `f_dom`, `a_dom`, `phi_start` | **yes** | — (hard error if missing) |
| `autocorrelation_lag1` | no | 0.8 |
| `outlier_rate`, `outlier_mean`, `outlier_std`, `outlier_skewness` | no | 0.0 |

This is exactly the format the `code3.json` already in this repo uses — unchanged by us.

## Building

```bash
cd andrey_hammer
make            # → build/andrey_hammer, no deps beyond libc + libm
```

## Testing

**Environment note:** this was developed against WSL2 Ubuntu, and — unusually
— that WSL2 kernel actually has DAMON support built in
(`CONFIG_DAMON=y`, `CONFIG_DAMON_VADDR=y`, `CONFIG_DAMON_SYSFS=y`, checked via
`zcat /proc/config.gz | grep -i damon`), and `damo` is preinstalled at
`/usr/local/bin/damo`. So the full pipeline can run right there — no separate
VM needed. It just needs an interactive `sudo` password, which an
unattended/background agent can't supply.

### Level 0 — no root needed

```bash
cd andrey_hammer && make
./build/andrey_hammer ../code3.json ../meta3.json /tmp/gt_test.log --steps 5 --seed 1
# expect: PID/REGION lines, "Total: 5 frames, N accesses simulated in real time"
# gt.log should have a "# region 0 base=... pages=..." header + N ts/region/page rows
```

```bash
python3 compare_io.py sim_raw3.txt sim_raw3.txt --no-heatmap
# expect: every metric = 1.00 / 0.000 (identical file vs itself)
```

**Before trusting numeric output past this level, resolve the "Known
issues" C-vs-Python mismatch above** — until then, `andrey_hammer`'s access
*counts* run ~1.5x hot relative to the reference model, even though it
mechanically runs fine.

### Level 1 — full live DAMON round-trip (needs root, run this yourself)

```bash
cd ~ && git clone --branch andrey_math --single-branch https://github.com/DanLyss/damoLoad.git
cd damoLoad
export DAMON_DIR=/usr/local/bin
sudo -E bash run_andrey.sh
# defaults to code3.json + meta3.json now. Builds andrey_hammer, runs it,
# records with a live `damo record` in parallel, compares against
# andrey_hammer's own gt.log via compare.py.
```

### Level 2 — fidelity check against the real original trace

```bash
sudo -E bash run_andrey.sh code3.json meta3.json /tmp/gt.log /root/andrey_out.data
python3 compare_io.py sim_raw3.txt /root/andrey_out.data --damo /usr/local/bin/damo
```

(`compare_io.py` auto-converts any input ending in `.data` through
`damo report access --raw`; anything else is read as io-format text directly.)

## Design decisions worth knowing before touching the code

- **Addresses are never reused literally.** `andrey_hammer` mmaps its own
  real region sized from the compressed geometry's *span* only. This was a
  deliberate choice (see `damo_replay.md` for the specific failure mode of
  `damo`'s own replay tool, which uses recorded addresses only as dictionary
  keys and never actually maps them — 0% spatial overlap with the original
  when independently observed).
- **The profile is computed in C, per frame, in real time** — not read from
  a pre-rendered Python-generated schedule file. This was also deliberate:
  the point is "how to hit memory right now," not "here's a script of what
  to do."
- **`gt.log` format is unchanged from `memtest`'s**, specifically so the
  existing `compare.py` works against `andrey_hammer`'s output with zero
  modification.
- **`compare_io.py` compares shape, not literal position** — because
  addresses don't match by design, everything is normalized to a 0..1
  fraction of each file's own address span before binning. Read the
  docstring at the top of the file for the exact reasoning.
