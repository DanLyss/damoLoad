# `damo replay` — what it is and how faithful it actually is

Notes from an investigation into the `replay` subcommand of
[damonitor/damo](https://github.com/damonitor/damo) (DAMON user-space tool),
done while evaluating whether it could stand in for `memtest`/`hammer` as a
way to regenerate a real workload's access pattern from a recorded
`damon.data` file.

## What it's supposed to do

`damo record` captures a running workload's access pattern into a file
(`damon.data` by default): a sequence of snapshots, each listing the DAMON
regions active in that window and how many times each was sampled as
accessed (`nr_accesses`).

`damo replay <record file>` reads that file back and tries to reproduce the
recorded accesses by making its own memory accesses, paced to match the
original timing — without needing the original workload binary running.
Introduced in damo v2.2.2, documented as an **experimental** feature.

## How it actually works

The implementation (`src/damo_replay.py`) keeps one process-global dict,
`page_map`, keyed by a "page frame number" computed as `recorded_address /
4096`. The first time a given recorded page is referenced, it lazily
allocates a fresh 4 KiB `bytearray` for that key and caches it; every later
reference to the same key reuses that same object. "Accessing" a region
means walking its recorded address range in 4 KiB steps and reading one byte
from the middle of the corresponding `bytearray`.

Playback walks the recorded snapshots one at a time. Each snapshot's real
duration is split into slices sized `aggr_interval / sample_interval` (e.g.
100ms / 5ms = 20 slices), mirroring DAMON's own sampling granularity. For
each slice, every region whose recorded `nr_accesses` count is greater than
the current slice index gets touched — touching means walking *every* page
in that region, not just the ones that were actually hot inside it. Pacing
between slices is a plain busy-wait spin comparing `time.time()` against the
slice deadline, with no catch-up logic if a slice runs long. Everything is
single-threaded.

The important consequence: **the recorded addresses are never actually
mapped into memory.** They're only ever used as dictionary keys. Wherever
CPython's own allocator happens to place the resulting `bytearray` objects
inside its heap — that's where the "access" really lands, and it has no
relationship to the original process's address space, which by replay time
usually doesn't even exist anymore (the original process has exited).

Two other things fall out of the code directly:
- Multiple monitoring records in one file are not supported — only
  `records[0]` is ever replayed, others are silently ignored.
- If a snapshot's regions take longer to walk than the slice budget, replay
  just runs behind schedule — there's no attempt to catch up, so under
  sufficient load the reproduced timing silently drifts from the original.

## What we measured

Setup: recorded a fixed, known workload (`memtest`'s hotspot config — 10
pages, 90% of traffic on pages 0-1, constant 150 Hz, 15s) with a real `damo
record`, fed the resulting `damon.data` into `damo replay`, and — instead of
trusting replay's own log output — attached a second, independent `damo
record` (adaptive `vaddr` mode, no address restriction) directly to the
running replay process to see what DAMON itself could observe from the
outside.

Results:
- **Spatial overlap with the original recording: 0%.** The replay process's
  real `/proc/<pid>/maps` never contains the originally recorded address
  range. The independent DAMON recording of the replay process found three
  regions instead — the interpreter's heap/loaded-libraries block, an mmap'd
  shared-library region, and (the hottest one, by far) the process **stack**
  — none of them anywhere near the original 40 KiB window.
- We also explicitly pointed a second `damo record --ops fvaddr` at the
  *exact original address range*, but targeting the replay process's PID.
  DAMON accepted the configuration without error, but reported flat **0 Hz
  access, every snapshot** — there's simply no mapped memory there in that
  process, so there's nothing to observe.
- **Bandwidth**: the original workload's DAMON-estimated average bandwidth
  was ~520 KiB/s. The replay process's *actual*, independently-observed
  bandwidth across its whole real address space averaged ~91 KiB/s (~18% of
  the original) — and most of that was the interpreter's own stack churn,
  not the intended simulated workload.
- **Timing** is the one thing that reproduced well: replay's wall-clock
  runtime (~14.1s) closely tracked the original recording's duration
  (~14.6s).

## Conclusion

`damo replay` is a timing/volume-paced synthetic load generator, not an
address-space reproducer. The relative proportion of "how often" each
recorded region is touched, relative to the others, is computed correctly
from the record — but "region" here is only a dictionary key inside the
replay process, with no page-level distinction preserved inside a region and
no connection to any real, externally-observable memory location. It cannot
be used to regenerate a heatmap that an independent DAMON instance (or any
other memory-access observer) would recognize as similar to the original. If
the goal is fidelity to a real address-space access pattern — which is what
`memtest`/`hammer` in this repo are for — `damo replay` is not a substitute.
