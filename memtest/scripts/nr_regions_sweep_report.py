#!/usr/bin/env python3
"""
nr_regions_sweep_report.py — render a PNG chart comparing ground truth
total accesses/sec over time against N separate DAMON recordings that
swept min_nr_regions/max_nr_regions (one recording per sweep point, each
with its own single-kdamond damo record + its own memtest run of the same
deterministic workload).

Usage:
  nr_regions_sweep_report.py <output.png> --sweep MIN1 MIN2 ... \
      --data DATA1 DATA2 ... --gt GT1 GT2 ...

  MINi   — the min_nr_regions value used for sweep point i (max = 5x, for
           the legend label only)
  DATAi  — damon.data file recorded for sweep point i
  GTi    — gt.log file from the memtest run for sweep point i
"""
import sys, os, subprocess, argparse

parser = argparse.ArgumentParser()
parser.add_argument('output_png')
parser.add_argument('--sweep', nargs='+', type=int, required=True)
parser.add_argument('--data', nargs='+', required=True)
parser.add_argument('--gt', nargs='+', required=True)
args = parser.parse_args()

if not (len(args.sweep) == len(args.data) == len(args.gt)):
    print('ERROR: --sweep, --data, --gt must all have the same count', file=sys.stderr)
    sys.exit(1)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
import compare  # reuse load_gt()

try:
    import _damo_records
except ImportError:
    out = subprocess.run(
        [sys.executable, '-c', 'import damo, os; print(os.path.dirname(damo.__file__))'],
        capture_output=True, text=True)
    pkg_dir = out.stdout.strip()
    if not pkg_dir:
        print(f'ERROR: could not locate damo package to import _damo_records:\n{out.stderr}',
              file=sys.stderr)
        sys.exit(1)
    sys.path.insert(0, pkg_dir)
    import _damo_records

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def build_gt_total_series(entries, dt_ns, n_buckets):
    # GT timestamps use memtest's own CLOCK_MONOTONIC — normalize relative
    # to this series' own first entry (not to any other clock domain).
    t0_ns = entries[0][0]
    counts = [0] * n_buckets
    for ts, _region, _page in entries:
        idx = (ts - t0_ns) // dt_ns
        if 0 <= idx < n_buckets:
            counts[idx] += 1
    bucket_sec = dt_ns / 1e9
    times = [(i + 0.5) * bucket_sec for i in range(n_buckets)]
    hz = [c / bucket_sec for c in counts]
    return times, hz


def damon_total_hz_series(record):
    # DAMON's snapshot.start_time comes from a different clock domain than
    # memtest's GT timestamps (ftrace/perf's own clock, not CLOCK_MONOTONIC
    # as seen by the traced process) — normalize relative to this record's
    # own first snapshot, not to GT's t0. Mixing the two raw clocks via a
    # shared min() previously caused a large, meaningless x-axis offset
    # between the GT and DAMON lines.
    # NOTE: do not weight by region.size() here. That would extrapolate
    # each region's sampled hit-rate across its *entire* byte range (this
    # repo's own patches/damo_report_heatmap.patch removed exactly this
    # weighting from the heatmap tool for the same reason: it estimates
    # bandwidth, not access count, and inflates whenever a region's real
    # hot spot is a small fraction of the region's size — which is
    # routinely true here, since hot/warm tracks use hotspot([0,1], 0.85)
    # inside regions up to 256 pages). Summing plain per-region Hz keeps
    # this a rough access-rate proxy, one representative sample per
    # currently-tracked region, comparable in kind to GT's literal count.
    # Use each snapshot's *actual* elapsed wall-clock duration
    # (end_time - start_time), not the nominal configured aggr_us. Under
    # heavy load (thousands of tracked regions), a single aggregation
    # cycle can take far longer than the configured interval — measured
    # up to ~7x longer in this repo's own 5500-region/min_nr_regions=5000
    # runs (mean ~417ms vs a nominal 100ms) — and nr_accesses.samples is
    # only meaningful relative to how long DAMON actually took to produce
    # it, not the interval it was asked for.
    t0_ns = record.snapshots[0].start_time
    times, hz = [], []
    for snap in record.snapshots:
        actual_aggr_us = (snap.end_time - snap.start_time) / 1000
        total_accesses_per_sec = sum(
            r.nr_accesses.in_hz(actual_aggr_us) for r in snap.regions
        )
        times.append((snap.start_time - t0_ns) / 1e9)
        hz.append(total_accesses_per_sec)
    return times, hz


series = []       # (min_r, damon_times, damon_hz)
gt_series = []     # (min_r, gt_times, gt_hz) -- one per run, since each run has its own GT

for min_r, data_path, gt_path in zip(args.sweep, args.data, args.gt):
    print(f'--- min_nr_regions={min_r} ---')
    print(f'  Loading GT: {gt_path}')
    _regions_meta, entries = compare.load_gt(gt_path)
    if not entries:
        print('  WARNING: ground truth empty, skipping this sweep point')
        continue
    print(f'  {len(entries)} accesses across {len(_regions_meta)} region(s)')

    print(f'  Loading DAMON record: {data_path}')
    records, err = _damo_records.get_records(record_file=data_path)
    if err or not records:
        print(f'  WARNING: could not load records ({err}), skipping this sweep point')
        continue
    record = records[0]

    aggr_us = record.intervals.aggr
    dt_ns = int(aggr_us * 1000)
    gt_dur_ns = entries[-1][0] - entries[0][0]
    n_buckets = max(1, int(gt_dur_ns / dt_ns) + 1)

    gt_times, gt_hz = build_gt_total_series(entries, dt_ns, n_buckets)
    damon_times, damon_hz = damon_total_hz_series(record)

    series.append((min_r, damon_times, damon_hz))
    gt_series.append((min_r, gt_times, gt_hz))

if not series:
    print('ERROR: no usable sweep points', file=sys.stderr)
    sys.exit(1)

# ── summary table ────────────────────────────────────────────────────────────
print()
print(f'{"config":>18}  {"mean Hz":>10}  {"GT mean Hz":>12}  {"mean |err|":>12}')
for (min_r, times, hz), (_, gt_times, gt_hz) in zip(series, gt_series):
    mean_hz = sum(hz) / len(hz) if hz else 0.0
    gt_mean = sum(gt_hz) / len(gt_hz) if gt_hz else 0.0
    dt = gt_times[1] - gt_times[0] if len(gt_times) > 1 else 1.0
    errs = []
    for t, h in zip(times, hz):
        idx = min(len(gt_hz) - 1, max(0, int(t / dt)))
        errs.append(abs(h - gt_hz[idx]))
    mean_err = sum(errs) / len(errs) if errs else float('nan')
    print(f'min={min_r:<6} max={min_r*5:<7}  {mean_hz:>10.1f}  {gt_mean:>12.1f}  {mean_err:>12.1f}')

# ── plot ──────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 6))

# sequential blue ramp, light -> dark, ordered by min_nr_regions ascending
ramp = ['#9ec5f4', '#5598e7', '#2a78d6', '#1c5cab', '#0d366b']
for (min_r, times, hz), color in zip(series, ramp):
    ax.plot(times, hz, color=color, linewidth=1.6,
            label=f'DAMON min_nr_regions={min_r} (max={min_r*5})')

# GT is (near-)identical across runs (deterministic workload) -- plot the
# one from the largest sweep point's run as the single reference trend
_, gt_times, gt_hz = gt_series[-1]
ax.plot(gt_times, gt_hz, color='black', linewidth=1.4, linestyle='--',
        label='Ground truth (real total accesses/sec)')

ax.set_xlabel('time (s)')
ax.set_ylabel('total accesses/sec (all regions summed)')
ax.set_title('DAMON aggregate access-rate fidelity vs min_nr_regions/max_nr_regions')
ax.legend(loc='upper right', fontsize=9)
ax.grid(True, linestyle=':', alpha=0.4)

fig.tight_layout()
fig.savefig(args.output_png, dpi=150)
print(f'\nChart saved: {args.output_png}')
