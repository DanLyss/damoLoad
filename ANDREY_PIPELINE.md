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
                          code3.json (passport) + meta.json (geometry)
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
| `code3.json` | Example/reference passport (10-channel statistical model) — see format below | Given, real |
| `generate.py (1).txt`, `reconstruct_heatmap.py.txt`, `format_raw.py.txt`, `simulate.py.txt` | Python reference implementation of the passport → synthetic io-format trace model (Modules 3/4/5). `simulate.py.txt` is the single-pass version combining all three | Given, real. **One-directional only** — passport → text, never a live process |
| `sim_raw3.txt` | A real example output of the Python model (io-format text, 254 snapshots) | Given, real — useful as a *shape reference*, not necessarily matched to `andrey_hammer/meta.example.json`'s geometry |
| `damo_replay.md` | Investigation notes: why `damo replay` (damo's own built-in replay subcommand) does NOT reproduce a real address-space pattern — motivates `andrey_hammer`'s design | Given, real |
| `compare.py`, `run_memtest.sh`, `memtest/`, `hammer/` | Pre-existing ground-truth-vs-DAMON tooling, unrelated to the passport model except that `andrey_hammer` reuses `compare.py`'s gt.log format and `memtest/scripts/build_kdamonds.py` | Given, real, unchanged |
| **`andrey_hammer/`** | **New.** C port of the passport model that drives LIVE memory accesses in real time (not a pre-rendered file). See `andrey_hammer/README.md` for full design rationale | **Built, compiled, smoke-tested** (see below) |
| **`run_andrey.sh`** | **New.** Automated build → run → `damo record` → compare orchestration, mirrors `run_memtest.sh` | **Built. NOT yet run end-to-end** (needs interactive `sudo` — see Testing) |
| **`compare_io.py`** | **New.** Direct io-format-vs-io-format shape comparison (Pearson r, cosine similarity, normalized RMSE, separate time/space-profile correlations, ASCII heatmap) | **Built, tested** against `sim_raw3.txt` (self-comparison and truncated-copy sanity checks) |
| **`andrey_hammer/meta.example.json`** | **New, placeholder only.** A made-up geometry file used purely to smoke-test that `andrey_hammer` runs at all. **Does NOT correspond to the real `code3.json`'s actual fitted geometry** — nobody has given us the real one yet | Fabricated for testing, not real data |

## What's missing

1. **The fitting step itself** (`io-format → code3.json` + `meta.json`) is confidential and lives outside this repo. Not our job to build.
2. **A real `meta.json`** matching the real `code3.json` — needed for any *meaningful* validation (does the reproduced trace actually look like the original). Without it we can only smoke-test that the machinery runs, using the fabricated `meta.example.json`.

## Exact file formats `andrey_hammer` expects

### `meta.json`

```json
{
    "super_gaussian_p": 6.0,
    "matrix_geometry": {
        "cols": 32,
        "rows": 254
    },
    "time_bounds_ms": {
        "start_ms": 0.0,
        "end_ms": 25654.0
    },
    "physical_bounds": {
        "active_min_addr": "0x556c637ac000",
        "active_max_addr": "0x556c63bac000"
    },
    "base_time_absolute": "2026-08-17T12:00:00"
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

### `code3.json`

10 required top-level keys: `w1, mu1, sigma1, w2, mu2, sigma2, w3, mu3, sigma3, M_raw`. Each is an object with:

| Field | Required? | Default |
|---|---|---|
| `trend_slope`, `trend_intercept`, `std_dev`, `skewness`, `f_dom`, `a_dom`, `phi_start` | **yes** | — (hard error if missing) |
| `autocorrelation_lag1` | no | 0.8 |
| `outlier_rate`, `outlier_mean`, `outlier_std`, `outlier_skewness` | no | 0.0 |

This is exactly the format the `code3.json` already in this repo uses — unchanged by us. If the real fitting script's output differs, it needs to be reshaped into this schema (or `andrey_hammer.c`'s `channel_precompute()` needs updating to match).

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

### Level 0 — no root needed (already done, safe to skip re-verifying)

```bash
cd andrey_hammer && make
./build/andrey_hammer code3.json meta.example.json /tmp/gt_test.log --steps 5 --seed 1
# expect: PID/REGION lines, "Total: 5 frames, N accesses simulated in real time"
# gt.log should have a "# region 0 base=... pages=..." header + N ts/region/page rows
```

```bash
python3 compare_io.py sim_raw3.txt sim_raw3.txt --no-heatmap
# expect: every metric = 1.00 / 0.000 (identical file vs itself)
```

### Level 1 — full live DAMON round-trip (needs root, run this yourself)

```bash
cd ~ && git clone --branch andrey_math --single-branch https://github.com/DanLyss/damoLoad.git
cd damoLoad
export DAMON_DIR=/usr/local/bin
sudo -E bash run_andrey.sh
# builds andrey_hammer, runs it against code3.json + andrey_hammer/meta.example.json,
# records with a live `damo record` in parallel, compares against andrey_hammer's
# own gt.log via compare.py. This validates the MACHINERY (does DAMON actually see
# what andrey_hammer does) — it does NOT validate that the reproduction matches a
# real original trace, because meta.example.json is fabricated (see above).
```

### Level 2 — meaningful fidelity check (needs a real `meta.json`)

Once a real `meta.json` (matching the real `code3.json`) is available:

```bash
sudo -E bash run_andrey.sh path/to/real_code3.json path/to/real_meta.json /tmp/gt.log /root/andrey_out.data
# then, comparing the fresh recording against the ORIGINAL trace's own io-format dump:
python3 compare_io.py path/to/original_trace.io.txt /root/andrey_out.data --damo /usr/local/bin/damo
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
