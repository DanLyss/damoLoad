#!/usr/bin/env python3
"""
compare_io.py — direct io-format vs io-format comparison.

Final step of the andrey_hammer pipeline:

    real damon.data           andrey_hammer's own damon.data
    (the ORIGINAL trace,      (whatever a live `damo record`
     before compression)       observed while replaying the
         │                      compressed passport)
         ▼                            ▼
    damo report access --raw_form    damo report access --raw_form
         │                            │
         └──────────── compare_io.py ────────────► report

Both inputs are in DAMON's own "raw" access-report text format:

    monitoring_start:  ...
    monitoring_end:    ...
    monitoring_duration: ...
    target_id: 0
    nr_regions: N
    # start_addr  end_addr  length  nr_accesses  age
    <hex>-<hex> (<size>) <nr_accesses> <age>
    ...
    <blank line>
    ... next snapshot ...

This is produced by `damo report access --input <damon.data> --raw`, and is
also exactly what this repo's model scripts (format_raw.py, simulate.py)
already emit directly — see sim_raw3.txt for a real example. A path ending
in `.data` is treated as a raw DAMON recording and piped through `damo
report access --raw_form` first; anything else is read as this text directly.

Why this can't be a literal address diff: andrey_hammer deliberately does
NOT reuse the original trace's literal virtual addresses (see
andrey_hammer/README.md — damo replay's failure mode is exactly this kind
of address confusion done badly). So every comparison here is a *shape*
comparison: each file's regions are normalized to a 0..1 fraction of that
file's own address span before binning, and what's compared is whether the
hot/cold structure over time and (relative) space matches — not whether
absolute addresses line up.
"""

import argparse
import math
import os
import re
import subprocess
import sys

# ── unit parsing ────────────────────────────────────────────────────────────

_SIZE_UNITS = {'b': 1, 'kib': 1024, 'mib': 1024**2, 'gib': 1024**3, 'tib': 1024**4}
_TIME_UNITS_TO_MS = {'ns': 1e-6, 'us': 1e-3, 'ms': 1.0, 's': 1e3, 'sec': 1e3}


def parse_size_to_bytes(text):
    text = text.strip()
    m = re.match(r'^([\d.]+)\s*([A-Za-z]+)$', text)
    if not m:
        return float(text)  # bare number, assume bytes
    val, unit = float(m.group(1)), m.group(2).lower()
    return val * _SIZE_UNITS.get(unit, 1)


def parse_time_to_ms(text):
    text = text.strip()
    m = re.match(r'^(-?[\d.]+)\s*([A-Za-z]+)$', text)
    if not m:
        return float(text)
    val, unit = float(m.group(1)), m.group(2).lower()
    return val * _TIME_UNITS_TO_MS.get(unit, 1.0)


# ── io-format parsing ───────────────────────────────────────────────────────

_REGION_RE = re.compile(
    r'^([0-9a-fA-F]+)-([0-9a-fA-F]+)\s*\(([^)]*)\)\s+(-?\d+)\s+(-?\d+)\s*$')


def parse_io_text(text):
    """Parses raw io-format text into a list of snapshots:
    {start_ms, end_ms, duration_ms, regions: [(start,end,nr_accesses,age)]}"""
    snapshots = []
    cur = None
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith('monitoring_start:'):
            cur = {'start_ms': parse_time_to_ms(line.split(':', 1)[1]), 'regions': []}
            snapshots.append(cur)
        elif cur is None:
            continue  # base_time_absolute / data source / stray header lines
        elif line.startswith('monitoring_end:'):
            cur['end_ms'] = parse_time_to_ms(line.split(':', 1)[1])
        elif line.startswith('monitoring_duration:'):
            cur['duration_ms'] = parse_time_to_ms(line.split(':', 1)[1])
        elif line.startswith('target_id:') or line.startswith('nr_regions:'):
            continue
        elif line.startswith('#'):
            continue
        else:
            m = _REGION_RE.match(line.strip())
            if not m:
                continue
            start = int(m.group(1), 16)
            end = int(m.group(2), 16)
            nr_acc = int(m.group(4))
            age = int(m.group(5))
            cur['regions'].append((start, end, nr_acc, age))
    for s in snapshots:
        if 'end_ms' not in s:
            s['end_ms'] = s['start_ms']
        if 'duration_ms' not in s:
            s['duration_ms'] = max(1e-6, s['end_ms'] - s['start_ms'])
    return [s for s in snapshots if s['regions']]


def load_io_format(path, damo_exe='damo', force_convert=None):
    is_raw_data = path.endswith('.data') if force_convert is None else force_convert
    if is_raw_data:
        cmd = [damo_exe, 'report', 'access', '--input', path, '--raw_form']
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            print(f'  ERROR running {" ".join(cmd)}:\n{res.stderr[:500]}', file=sys.stderr)
            sys.exit(1)
        text = res.stdout
    else:
        with open(path) as f:
            text = f.read()
    return parse_io_text(text)


# ── grid construction (time × normalized-address-fraction, weighted overlap) ─

def snapshot_row_weights(snapshots, t_rows, t0, t1):
    """For each snapshot, list of (row_index, weight) pairs — weight is the
    fraction of that snapshot's duration falling inside each time row."""
    dur = t1 - t0
    out = []
    for s in snapshots:
        weights = []
        if dur <= 0:
            weights.append((0, 1.0))
            out.append(weights)
            continue
        r_lo = (s['start_ms'] - t0) / dur * t_rows
        r_hi = (s['end_ms'] - t0) / dur * t_rows
        r_lo, r_hi = max(0.0, r_lo), min(float(t_rows), r_hi)
        if r_hi <= r_lo:
            r_hi = r_lo + 1e-6
        for r in range(int(r_lo), min(t_rows, int(math.ceil(r_hi)))):
            overlap = min(r + 1.0, r_hi) - max(float(r), r_lo)
            if overlap > 0:
                weights.append((r, overlap / (r_hi - r_lo)))
        if not weights:
            weights.append((min(t_rows - 1, int(r_lo)), 1.0))
        out.append(weights)
    return out


def region_col_weights(start, end, addr_lo, addr_span, s_cols):
    if addr_span <= 0:
        return [(0, 1.0)]
    f_lo = (start - addr_lo) / addr_span * s_cols
    f_hi = (end - addr_lo) / addr_span * s_cols
    f_lo, f_hi = max(0.0, f_lo), min(float(s_cols), f_hi)
    if f_hi <= f_lo:
        f_hi = f_lo + 1e-6
    weights = []
    for c in range(int(f_lo), min(s_cols, int(math.ceil(f_hi)))):
        overlap = min(c + 1.0, f_hi) - max(float(c), f_lo)
        if overlap > 0:
            weights.append((c, overlap))
    if not weights:
        weights.append((min(s_cols - 1, int(f_lo)), f_hi - f_lo))
    return weights


def build_grid(snapshots, t_rows, s_cols):
    if not snapshots:
        return [[0.0] * s_cols for _ in range(t_rows)], None

    t0 = snapshots[0]['start_ms']
    t1 = snapshots[-1]['end_ms']
    addr_lo = min(r[0] for s in snapshots for r in s['regions'])
    addr_hi = max(r[1] for s in snapshots for r in s['regions'])
    addr_span = addr_hi - addr_lo

    row_w = snapshot_row_weights(snapshots, t_rows, t0, t1)
    grid = [[0.0] * s_cols for _ in range(t_rows)]

    total_accesses = 0
    total_regions = 0
    ages = []
    for s, rw in zip(snapshots, row_w):
        for (start, end, nr_acc, age) in s['regions']:
            total_accesses += nr_acc
            total_regions += 1
            ages.append(age)
            col_w = region_col_weights(start, end, addr_lo, addr_span, s_cols)
            for (row, tw) in rw:
                for (col, sw) in col_w:
                    grid[row][col] += nr_acc * tw * sw

    row_dur_sec = max(1e-9, (t1 - t0) / 1000.0 / t_rows)
    hz_grid = [[v / row_dur_sec for v in row] for row in grid]

    meta = {
        't0_ms': t0, 't1_ms': t1, 'addr_lo': addr_lo, 'addr_hi': addr_hi,
        'total_accesses': total_accesses, 'n_snapshots': len(snapshots),
        'mean_regions_per_snap': total_regions / len(snapshots),
        'mean_age': sum(ages) / len(ages) if ages else 0.0,
        'max_age': max(ages) if ages else 0,
    }
    return hz_grid, meta


# ── metrics ──────────────────────────────────────────────────────────────────

def flatten(grid):
    return [v for row in grid for v in row]


def pearson(a, b):
    n = len(a)
    if n == 0:
        return float('nan')
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return float('nan')
    return cov / math.sqrt(va * vb)


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return float('nan')
    return dot / (na * nb)


def col_marginal(grid, s_cols):
    return [sum(row[c] for row in grid) for c in range(s_cols)]


def row_marginal(grid):
    return [sum(row) for row in grid]


# ── ASCII rendering (same palette as compare.py) ────────────────────────────

_C = [
    '\033[38;5;232m0\033[0m', '\033[38;5;235m1\033[0m', '\033[38;5;238m2\033[0m',
    '\033[38;5;241m3\033[0m', '\033[38;5;244m4\033[0m', '\033[38;5;247m5\033[0m',
    '\033[38;5;250m6\033[0m', '\033[38;5;253m7\033[0m', '\033[1;38;5;255m8\033[0m',
    '\033[1;97m9\033[0m',
]


def shade(hz, min_hz, max_hz):
    if max_hz <= min_hz:
        return _C[0]
    level = int((hz - min_hz) / (max_hz - min_hz) * 9 + 0.5)
    return _C[min(9, max(0, level))]


def render(grid, t_rows, s_cols, title, min_hz, max_hz):
    print(f'\n  {title}')
    for t in range(t_rows):
        row = '  '
        for s in range(s_cols):
            row += shade(grid[t][s], min_hz, max_hz)
        print(row)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file_a', help='original io-format file (or .data, auto-converted)')
    ap.add_argument('file_b', help='reproduced io-format file (or .data, auto-converted)')
    ap.add_argument('--rows', type=int, default=30, help='time resolution (default: 30)')
    ap.add_argument('--cols', type=int, default=20, help='address-fraction resolution (default: 20)')
    ap.add_argument('--damo', default='damo', help='damo executable (for .data inputs)')
    ap.add_argument('--convert-a', action='store_true', help='force A through `damo report access --raw_form`')
    ap.add_argument('--convert-b', action='store_true', help='force B through `damo report access --raw_form`')
    ap.add_argument('--no-heatmap', action='store_true', help='skip ASCII heatmap rendering')
    ap.add_argument('--markdown', action='store_true',
                     help='also print a "| label | shape r | space r | time r | ratio |" row, '
                          'for collecting multiple runs into one comparison table')
    ap.add_argument('--markdown-header', action='store_true',
                     help='with --markdown, also print the table header + separator row first')
    ap.add_argument('--label', default=None,
                     help='row label for --markdown (default: "<A> vs <B>" using basenames)')
    args = ap.parse_args()

    print(f'Loading A: {args.file_a}')
    snaps_a = load_io_format(args.file_a, args.damo, args.convert_a or None)
    print(f'Loading B: {args.file_b}')
    snaps_b = load_io_format(args.file_b, args.damo, args.convert_b or None)

    if not snaps_a or not snaps_b:
        print('ERROR: one of the inputs has no parsable snapshots.')
        sys.exit(1)

    grid_a, meta_a = build_grid(snaps_a, args.rows, args.cols)
    grid_b, meta_b = build_grid(snaps_b, args.rows, args.cols)

    fa, fb = flatten(grid_a), flatten(grid_b)
    max_a, max_b = max(fa) or 1.0, max(fb) or 1.0
    fa_norm = [v / max_a for v in fa]
    fb_norm = [v / max_b for v in fb]

    r_raw = pearson(fa, fb)
    r_norm = pearson(fa_norm, fb_norm)
    cos_sim = cosine(fa_norm, fb_norm)
    rmse_norm = math.sqrt(sum((x - y) ** 2 for x, y in zip(fa_norm, fb_norm)) / len(fa_norm))

    row_a, row_b = row_marginal(grid_a), row_marginal(grid_b)
    col_a, col_b = col_marginal(grid_a, args.cols), col_marginal(grid_b, args.cols)
    r_time = pearson(row_a, row_b)
    r_space = pearson(col_a, col_b)

    total_a, total_b = meta_a['total_accesses'], meta_b['total_accesses']
    ratio = total_b / total_a if total_a else float('nan')

    print(f'\n  A: {meta_a["n_snapshots"]} snapshots, span '
          f'{(meta_a["addr_hi"] - meta_a["addr_lo"]) / 1024:.1f} KiB, '
          f'{total_a} total accesses')
    print(f'  B: {meta_b["n_snapshots"]} snapshots, span '
          f'{(meta_b["addr_hi"] - meta_b["addr_lo"]) / 1024:.1f} KiB, '
          f'{total_b} total accesses')

    print(f'\n┌ Shape similarity ({args.rows}×{args.cols} grid, address-normalized) ─')
    print(f'│  Pearson r (raw):        {r_raw:6.3f}')
    print(f'│  Pearson r (normalized): {r_norm:6.3f}')
    print(f'│  Cosine similarity:      {cos_sim:6.3f}')
    print(f'│  Normalized RMSE:        {rmse_norm:6.3f}  (0 = identical shape, 1 = orthogonal-scale)')
    print(f'│  Time-profile r:         {r_time:6.3f}   (does activity rise/fall together over time)')
    print(f'│  Space-profile r:        {r_space:6.3f}   (does the same relative region stay hot)')
    print('└' + '─' * 60)

    print(f'\n┌ Magnitude ─────────────────────────────────────────────')
    print(f'│  Total accesses   A: {total_a:>8}   B: {total_b:>8}   ratio B/A: {ratio:.2f}')
    print(f'│  Mean age         A: {meta_a["mean_age"]:>8.2f}   B: {meta_b["mean_age"]:>8.2f}')
    print(f'│  Max age          A: {meta_a["max_age"]:>8}   B: {meta_b["max_age"]:>8}')
    print(f'│  Regions/snapshot A: {meta_a["mean_regions_per_snap"]:>8.1f}   B: {meta_b["mean_regions_per_snap"]:>8.1f}')
    print('└' + '─' * 60)

    if not args.no_heatmap:
        all_vals = fa + fb
        nonzero = [v for v in all_vals if v > 0]
        min_hz = 0.0
        max_hz = max(nonzero) if nonzero else 1.0
        print(f'\n  scale: 0={min_hz:.1f} Hz  ...  9={max_hz:.1f} Hz  (shared across both)')
        render(grid_a, args.rows, args.cols, 'A — original', min_hz, max_hz)
        render(grid_b, args.rows, args.cols, 'B — reproduced', min_hz, max_hz)

    print()
    if math.isnan(r_norm):
        print('VERDICT: not enough variance to judge shape similarity.')
    elif r_norm > 0.7 and 0.5 < ratio < 2.0:
        print(f'VERDICT: strong match — shape r={r_norm:.2f}, magnitude within 2x (ratio={ratio:.2f}).')
    elif r_norm > 0.4:
        print(f'VERDICT: partial match — shape r={r_norm:.2f} is positive but not strong; '
              f'check magnitude ratio ({ratio:.2f}) and per-axis r above for where it diverges.')
    else:
        print(f'VERDICT: weak/no match — shape r={r_norm:.2f}. '
              f'Check time-profile r ({r_time:.2f}) vs space-profile r ({r_space:.2f}) '
              f'to see whether the mismatch is temporal, spatial, or both.')

    if args.markdown:
        label = args.label or f'{os.path.basename(args.file_a)} vs {os.path.basename(args.file_b)}'
        print()
        if args.markdown_header:
            print('| Compare | Shape r | Space r | Time r | Magnitude ratio |')
            print('|---|---|---|---|---|')
        print(f'| {label} | {r_norm:.2f} | {r_space:.2f} | {r_time:.2f} | {ratio:.2f} |')


if __name__ == '__main__':
    main()
