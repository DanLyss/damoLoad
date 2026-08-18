# Andrey pipeline — status & handoff

This document exists so a new agent/dev can pick up this branch (`andrey_math`)
without re-deriving context from git history or chat logs. It covers: what
the pipeline is, what's built, what's validated, what's still missing, exact
file formats, and exact commands to build/run/test everything.

## The pipeline — overview

**Two different things read the same `code3.json`+`meta3.json`.** Andrey's
own pipeline (Python, offline, never touches real memory) and this repo's
pipeline (C, live, real memory, real DAMON) are separate, parallel paths —
not stages of one linear flow. Both end at an io-format text file, which is
why `compare_io.py` can point at either one:

```
                    ┌─────────────────────────────────────┐
                    │  CONFIDENTIAL — not in this repo,    │
  real damon.data   │  not our concern to build             │
  (io format)  ─────┼─►  fitting script (Python) reduces a  │
                    │    full trace to a small statistical   │
                    │    "passport"                          │
                    └───────────────────┬───────────────────┘
                                         ▼
                          code3.json (passport) + meta3.json (geometry)
                                         │
                    ┌────────────────────┴────────────────────┐
                    ▼                                          ▼
     ANDREY'S PIPELINE (Python, offline)      THIS REPO'S PIPELINE (C, live, real DAMON)
     ───────────────────────────────────      ──────────────────────────────────────────
     generate.py (1).txt computes the          andrey_hammer computes the same profile,
     profile offline and formats it            per frame, in real time, and immediately
     straight to text — nothing is             touches real memory pages with it — see
     executed, it's a prediction               "This repo's pipeline" below for detail
                    │                                          │
                    ▼                                          ▼
         io-format TEXT (sim_raw3.txt)              io-format TEXT (two ways to get one,
                                                      see below — with or without DAMON)
                    │                                          │
                    └────────────────────┬────────────────────┘
                                         ▼
                                  compare_io.py
                            (shape comparison of any
                              two io-format files)
                                         ▼
                                   final report
```

The rest of this section breaks each branch down.

### Andrey's pipeline, in detail

```
code3.json + meta3.json
        │
        ▼
generate.py (1).txt   — Module 3+4+5 combined: synthesizes the 10-channel
        │                trajectory, expands it into a spatial profile,
        │                formats it into region/nr_accesses/age text —
        │                all in one offline pass
        ▼
sim_raw3.txt-style io-format TEXT FILE   (a *prediction*, never executed)
```
(equivalently, the same three steps run separately: `simulate.py.txt`
(despite the name — Module 3 only, → trajectory CSV) → `reconstruct_heatmap.py.txt`
(→ raw heatmap CSV) → `format_raw.py.txt` (→ io-format text); see "Filename
trap" below before trusting either file's name over its docstring)

### This repo's pipeline, in detail

```
code3.json + meta3.json
        │
        ▼
andrey_hammer (C)      — same math, ported to C, computed fresh every frame,
        │                immediately acted on: mmaps a real region and
        │                writes real bytes to real pages RIGHT NOW
        ▼
gt.log + gt.log.frames (exactly what andrey_hammer really did)
        │
        ├──────────────────────► gt_to_io.py ──► io-format text (DAMON-free)
        │
        └── watched live by `damo record` ──► damon.data ──► `damo report
                                                access --raw` ──► io-format
                                                text (DAMON's observation,
                                                with its own 5ms/200Hz
                                                sampling noise baked in)
```

`run_andrey.sh` automates the right-hand (DAMON) route end to end: build →
run `andrey_hammer` → `damo record` in parallel → GT-vs-DAMON compare
(`compare.py`) → materialize io-format (`damo report access --raw`) →
io-vs-io compare (`compare_io.py`) against `sim_raw3.txt`.

**Three different comparisons, three different questions** — all via
`compare_io.py`, just pointed at different pairs of io-format files:

| Compare | Answers |
|---|---|
| `sim_raw3.txt` vs `gt_to_io.py` output | Does the C math port match the Python reference? (no DAMON either side) |
| `sim_raw3.txt` vs `damo report access --raw` output | Does DAMON's *observation* of the live replay match the original? (DAMON's 5ms/200Hz sampling noise included) |
| `gt_to_io.py` output vs `damo report access --raw` output | How much noise does DAMON's own sampling add, isolated from everything else? |

## What's in this repo, file by file

| Path | What it is | Status |
|---|---|---|
| `code3.json` | Real passport (10-channel statistical model) — see format below | Given, real |
| `meta3.json` | Real geometry matching `code3.json` — confirmed: its address span (696320 B = 680 KiB) matches `sim_raw3.txt` exactly, so this is the geometry that produced it | Given, real |
| `sim_raw3.txt` | Real example output of the Python model on `code3.json`+`meta3.json` (io-format text, 254 snapshots) | Given, real — use as the shape reference |
| `damo_replay.md` | Investigation notes: why `damo replay` (damo's own built-in replay subcommand) does NOT reproduce a real address-space pattern — motivates `andrey_hammer`'s design | Given, real |
| `compare.py`, `scripts/build_kdamonds.py`, `patches/` | Pre-existing DAMON-comparison tooling this pipeline reuses (gt.log-vs-DAMON heatmap renderer, kdamonds JSON builder, required damo patches). An older, unrelated `memtest`/`hammer`/`run_memtest.sh` project used to live in this repo alongside these — removed from this branch since it's not part of the passport pipeline; only these two files were actual dependencies | Given, real, unchanged |
| **`andrey_hammer/`** | **New.** C port of the passport model that drives LIVE memory accesses in real time (not a pre-rendered file). See `andrey_hammer/README.md` for full design rationale | **Built, compiled, checked against `sim_raw3.txt` on real `code3.json`+`meta3.json`: spatial-profile r=0.89, magnitude within ~4% once width-weighted (see "Known issues"). Time-axis fidelity still degraded by a real pacing bug** |
| **`run_andrey.sh`** | **New.** Automated build → run → `damo record` → compare orchestration | **Built. NOT yet run end-to-end** (needs interactive `sudo` — see Testing) |
| **`compare_io.py`** | **New.** Direct io-format-vs-io-format shape comparison (Pearson r, cosine similarity, normalized RMSE, separate time/space-profile correlations, ASCII heatmap) | **Built, tested** — self-comparison sanity checks, and used for the C-vs-Python math check below |
| **`andrey_hammer/gt_to_io.py`** | **New.** Converts `gt.log`+`gt.log.frames` into io-format text directly, no DAMON involved — isolates replay fidelity from DAMON's own measurement noise | **Built, tested** — see "Known issues" below (r=0.97 vs `sim_raw3.txt`) |

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

## Known issues

**Apparent C-vs-Python total-accesses mismatch — investigated, turned out
NOT to be a math bug.** First pass looked alarming: `andrey_hammer` vs the
Python reference on the same `code3.json`+`meta3.json`, 254 steps, naive
`sum(nr_accesses)` over all regions gave 55737 (C) vs 27625 (Python,
`sim_raw3.txt`) — a consistent ~2x gap across multiple seeds. Root cause:
`format_raw.py`'s region-merging step (and `generate.py (1).txt`'s inline
equivalent) collapses adjacent same-valued spatial bins into one wider
region and writes **one** `nr_accesses` value for the whole merged region —
correct DAMON semantics (`nr_accesses` is a rate for the region, not summed
across its width), but it means a naive `sum(nr_accesses)` over a merged
io-format file systematically undercounts relative to `andrey_hammer`'s
`gt.log`, which logs literal unmerged per-page touches. Width-weighting
fixes it:

```
naive sum(nr_accesses) over regions:                 27625
width-weighted sum(nr_accesses × pages_in_region):    53811   ← vs C's 55737, ~4% gap
```

4% is within normal seed-to-seed variance (~10-12% spread observed across 5
seeds). **Conclusion: the math port's magnitude looks correct.** Spatial
shape also checks out: `compare_io.py`-style spatial-profile Pearson r =
0.89 between `andrey_hammer`'s live touches and `sim_raw3.txt`, on the real
`code3.json`+`meta3.json`. Lesson for future comparisons: don't compare raw
`sum(nr_accesses)` between a merged (`damo`/Python-style) io-format file and
an unmerged ground-truth log without width-weighting one side — `compare_io.py`
itself isn't affected by this for its real use case (both sides of a Level-2
comparison go through `damo report access --raw`, so both are merged the
same way and stay comparable).

**Real, still-open issue: timing drift in the live pacing loop.** Under
WSL2, `andrey_hammer.c`'s per-frame `sleep_ns(remaining_ns)` padding runs
~20–30% over its nominal `frame_dt_ms` (measured directly, not inferred —
`andrey_hammer` now writes `<gt.log>.frames` with each frame's real
`start_ns`/`end_ns`; a 100.46ms nominal frame measured out to ~124ms
actual in one run). It doesn't carry debt across frames — each frame just
pads with whatever time is left, so overruns compound instead of being
caught up. This degrades any comparison against *nominal* frame boundaries
(time-profile r ~0.43 vs spatial r ~0.89 on otherwise-matching data, see
`gt_to_io.py` below which sidesteps this by using the real `.frames`
boundaries instead of nominal ones). Worth fixing with a debt-based pacing
loop (accumulate `elapsed - frame_dt_ms` and let it eat into the next
frame's budget, the same idea used elsewhere in this codebase for
sub-frame access pacing) before trusting time-axis comparisons against
nominal boundaries.

**`andrey_hammer/gt_to_io.py`** — converts `gt.log` + `gt.log.frames`
straight into an io-format text file, bypassing DAMON's own 5ms/200Hz
sampling entirely. Useful for separating two different questions: "did
`andrey_hammer`'s replay match the original passport's model" (this
script, no DAMON noise) vs "did DAMON *observe* that replay correctly"
(the `damo report access --raw` path `run_andrey.sh` already uses). On the
real `code3.json`+`meta3.json` vs `sim_raw3.txt`: spatial r=1.00, overall
shape r=0.97, magnitude ratio 1.06 — confirms the earlier finding (math
port looks correct) with a cleaner, DAMON-noise-free measurement.

```bash
python3 andrey_hammer/gt_to_io.py --gt gt.log --frames gt.log.frames --meta meta3.json --output gt_as_io.txt
python3 compare_io.py sim_raw3.txt gt_as_io.txt
```

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

See "Known issues" above for what's already validated math-wise (spatial
shape and magnitude check out; time-axis pacing doesn't yet).

### Level 1 — full live DAMON round-trip (needs root, run this yourself)

```bash
cd ~ && git clone --branch andrey_math --single-branch https://github.com/DanLyss/damoLoad.git
cd damoLoad
export DAMON_DIR=/usr/local/bin
sudo -E bash run_andrey.sh
```

Defaults to `code3.json` + `meta3.json` + `sim_raw3.txt` as the original.
Does everything in one go: builds `andrey_hammer`, runs it, records with a
live `damo record` in parallel, compares against `andrey_hammer`'s own
`gt.log` via `compare.py`, **then** converts the fresh recording to
io-format text (`damo report access --raw`) and runs `compare_io.py`
against the original — the actual final "two io-format files → report"
step from the original pipeline spec. Both reports get saved under
`andrey_hammer/results/`.

To point at a different original trace or output paths:

```bash
sudo -E bash run_andrey.sh code3.json meta3.json /tmp/gt.log /root/andrey_out.data path/to/original.io.txt
```

(`compare_io.py` itself also auto-converts any input ending in `.data`
through `damo report access --raw` if called standalone; anything else is
read as io-format text directly.)

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
- **`gt.log`'s format (`# region N base=... pages=...` + `ts_ns region page`
  rows) matches what `compare.py` already expects**, so it works against
  `andrey_hammer`'s output with zero modification.
- **`compare_io.py` compares shape, not literal position** — because
  addresses don't match by design, everything is normalized to a 0..1
  fraction of each file's own address span before binning. Read the
  docstring at the top of the file for the exact reasoning.
