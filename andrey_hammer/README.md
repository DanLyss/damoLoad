# andrey_hammer — real-time JIT load simulator from a compressed passport

> See [`../ANDREY_PIPELINE.md`](../ANDREY_PIPELINE.md) for the full pipeline,
> status, and test commands, and [`PACING_DRIFT_ISSUE.md`](PACING_DRIFT_ISSUE.md)
> for the (now fixed) real-time pacing investigation.

A single-file C program that consumes Andrey's compressed statistical model
of a DAMON trace (`code3.json` passport + `meta.json` geometry) and turns it
into **live memory accesses, right now** — no pre-generated schedule file,
no Python at runtime. Meant to sit at the "C program" stage of the pipeline:

```
real damon.data (io format)
      │  confidential fitting script (not in this repo)
      ▼
code3.json + meta.json  ────────────►  andrey_hammer  ────► live accesses
      (compressed info)                (this program)         on real pages
                                                                     │
                                                     independent `damo record`
                                                                     ▼
                                                          fresh damon.data
```

## Why it computes the profile itself, in C, per second

The existing Python modules in this repo (`generate.py`, `reconstruct_heatmap.py`,
`simulate.py.txt`) already implement this same model — but they write a
*synthetic io-format text file* (see `sim_raw3.txt`). That's a description of
a trace, not a trace happening. `andrey_hammer` ports the same math
(3-mode Super-Gaussian spatial mixture, cascaded AR(1) temporal fluctuation
with split-normal innovations, harmonic component, outliers — see the header
comment in `src/andrey_hammer.c` for the exact correspondence to
`generate.py`/`reconstruct_heatmap.py`) into C so the profile for "this
second" is computed and immediately acted on, in the same process that's
touching memory, at wall-clock cadence.

## Why it doesn't reuse the original literal addresses

See [`../damo_replay.md`](../damo_replay.md): `damo replay` uses recorded
addresses only as dictionary keys, never actually mapping them — an
independent DAMON observer sees 0% spatial overlap with the original trace.
`andrey_hammer` avoids that failure mode differently: it `mmap`s its **own**
real, page-backed anonymous region, sized from the compressed geometry
(`meta.matrix_geometry` / `physical_bounds` span), and reproduces the
model's per-bin access profile as literal writes to literal pages inside
*that* region. What DAMON observes is real, externally-verifiable traffic —
just not at the original process's literal VA. The original addresses are
used only for their *span* (to size our region) and implicitly through
`matrix_geometry.cols` (to lay out spatial bins proportionally) — never as
a `MAP_FIXED` target.

## Build

```bash
cd andrey_hammer
make
```

Produces `build/andrey_hammer`. No dependencies beyond libc + libm.

## Input files

### `meta.json` (geometry — required keys)

| Key | Description |
|---|---|
| `matrix_geometry.cols` | number of spatial bins across the address span |
| `matrix_geometry.rows` | number of time frames the passport was fit over |
| `super_gaussian_p` | shape parameter of the spatial mixture (matches `generate.py`) |
| `time_bounds_ms.{start_ms,end_ms}` or `time_bounds_us.{start_us,end_us}` | defines frame duration = `(end-start)/rows` |
| `physical_bounds.{active_min_addr,active_max_addr}` **or** `start_addr`/`end_addr` | address span — only the *size* is used, see above |

### `code3.json` (passport — 10 required channels)

`w1, mu1, sigma1, w2, mu2, sigma2, w3, mu3, sigma3, M_raw` — each an object
with `trend_slope`, `trend_intercept`, `std_dev`, `skewness`, `f_dom`,
`a_dom`, `phi_start` (required), plus optional `autocorrelation_lag1`
(default 0.8), `outlier_rate`/`outlier_mean`/`outlier_std`/`outlier_skewness`
(default 0). Same schema `generate.py`/`simulate.py.txt` already consume —
this is the exact file the (external, confidential) fitting step produces.

## Usage

```bash
./build/andrey_hammer [--auto] code3.json meta.json [gt.log]
                       [--seed N] [--steps N] [--extrapolation-factor F]
                       [--time-step-ratio R] [--legacy-clip]
```

| Flag | Default | Meaning |
|---|---|---|
| `--auto` | off | print `# PID=`/`# REGION`/`# READY` markers and wait for `SIGUSR1` instead of Enter — for scripted orchestration (see `run_andrey.sh`) |
| `--seed` | 0 | RNG seed (reproducible *within* this binary; not bit-comparable to the Python model's own RNG stream) |
| `--steps` | — | explicit frame count, overrides `rows × extrapolation-factor` |
| `--extrapolation-factor` | 1.0 | run for longer/shorter than the fitted trace by this factor |
| `--time-step-ratio` | 1.0 | scales `dt` (and therefore frame duration) relative to the passport's native cadence |
| `--legacy-clip` | off | clip `M_raw` to `cols × 9` instead of leaving it open-ended |

Manual example:

```bash
# terminal 1
./build/andrey_hammer code3.json meta.json /tmp/gt.log
# PID:      12345
# Region:   0x7f.....-0x7f.....  (...)
# (press Enter once DAMON is attached)

# terminal 2 (root)
damo record --ops fvaddr --target_pid 12345 -r 0x7f...-0x7f... \
    --monitoring_intervals 5ms 100ms 1s --timeout 30 -o /tmp/andrey.data

# after both finish
python3 ../compare.py /tmp/andrey.data /tmp/gt.log
```

`gt.log` is written in the exact format `../compare.py` already expects
(`# region 0 base=0x.. pages=..` header + `ts_ns region page` rows), so the
existing comparison tooling works against it unmodified. Alongside it,
`andrey_hammer` also writes `<gt.log>.frames` (real, not nominal, per-frame
start/end timestamps) — `gt_to_io.py` in this directory converts that pair
straight into io-format text, bypassing DAMON entirely:

```bash
python3 gt_to_io.py --gt /tmp/gt.log --frames /tmp/gt.log.frames \
    --meta meta.json --output /tmp/gt_as_io.txt
python3 ../compare_io.py ../sim_raw3.txt /tmp/gt_as_io.txt
```

For the fully automated version (build → run → `damo record` → all
comparisons in one command), see `../run_andrey.sh`.
