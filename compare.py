#!/usr/bin/env python3
"""
compare.py — side-by-side GT vs DAMON heatmaps, same T×S resolution.

Usage:
  python3 compare.py damon_data gt.log [time_rows] [space_cols] [damon_base] [damon_max]

One heatmap per region, regardless of region count.
damo report heatmap is called ONCE at page-level resolution; pixels are
filtered per region from the cached result.
"""

import sys, subprocess, collections, math

# ── color palette ─────────────────────────────────────────────────────────────
_C = [
    '\033[38;5;232m0\033[0m',   # #080808 — cold
    '\033[38;5;235m1\033[0m',   # #262626
    '\033[38;5;238m2\033[0m',   # #444444
    '\033[38;5;241m3\033[0m',   # #626262
    '\033[38;5;244m4\033[0m',   # #808080
    '\033[38;5;247m5\033[0m',   # #9e9e9e
    '\033[38;5;250m6\033[0m',   # #bcbcbc
    '\033[38;5;253m7\033[0m',   # #dadada
    '\033[1;38;5;255m8\033[0m', # #eeeeee bold
    '\033[1;97m9\033[0m',       # bright white bold — hot
]

def shade(hz, min_hz, max_hz):
    if max_hz <= min_hz:
        return _C[0]
    level = int((hz - min_hz) / (max_hz - min_hz) * 9 + 0.5)
    return _C[min(9, max(0, level))]


# ── GT loading ────────────────────────────────────────────────────────────────

def load_gt(path):
    regions_meta = []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('# region'):
                parts = line.split()
                ridx = int(parts[2])
                base = int(parts[3].split('=')[1], 16)
                npg  = int(parts[4].split('=')[1])
                while len(regions_meta) <= ridx:
                    regions_meta.append(None)
                regions_meta[ridx] = (base, npg)
            elif line.startswith('#'):
                continue
            else:
                parts = line.split()
                if len(parts) >= 3:
                    entries.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return regions_meta, entries


def build_gt_grid(entries, region_idx, n_pages, t_rows, s_cols, t0_ns, t1_ns):
    """
    Weighted overlap GT heatmap.
    hz = sum(overlap(col, page) * hits) / bucket_sec
    """
    dur_ns = t1_ns - t0_ns
    if dur_ns <= 0:
        return [[0.0] * s_cols for _ in range(t_rows)]

    page_counts = collections.defaultdict(int)
    for ts, reg, page in entries:
        if reg != region_idx:
            continue
        t_frac = (ts - t0_ns) / dur_ns
        t_idx = min(t_rows - 1, int(t_frac * t_rows))
        page_counts[(t_idx, page)] += 1

    col_weights = []
    for s in range(s_cols):
        p_lo = s * n_pages / s_cols
        p_hi = (s + 1) * n_pages / s_cols
        weights = []
        for p in range(int(p_lo), min(n_pages, int(p_hi) + 1)):
            overlap = min(p + 1.0, p_hi) - max(p, p_lo)
            if overlap > 0:
                weights.append((p, overlap))
        col_weights.append(weights)

    bucket_sec = (dur_ns / 1e9) / t_rows
    grid = [
        [sum(w * page_counts[(t, p)] for p, w in col_weights[s]) / bucket_sec
         for s in range(s_cols)]
        for t in range(t_rows)
    ]
    return grid


# ── DAMON heatmap — one call per region via damo --address_range ──────────────

def build_damon_grid(damon_path, t_rows, s_cols, addr_start=None, addr_end=None, damo_exe='damo'):
    """
    Run damo report heatmap scoped to [addr_start, addr_end) using damo's own
    --address_range option.  damo bins the data into t_rows × s_cols pixels;
    we just parse the raw output directly into a grid.
    """
    cmd = [damo_exe, 'report', 'heatmap',
           '--input', damon_path,
           '--resol', str(t_rows), str(s_cols),
           '--output', 'raw']
    if addr_start is not None and addr_end is not None:
        cmd += ['--address_range', str(addr_start), str(addr_end)]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f'  damo report heatmap failed: {e}')
        return None
    if res.returncode != 0:
        print(f'  damo report heatmap error:\n{res.stderr[:300]}')
        return None

    pixels = []
    for line in res.stdout.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[2] != 'NaN':
            try:
                pixels.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
    if not pixels:
        return None

    # damo outputs time and addr as relative offsets (abs_time/abs_addr default False).
    # Remap to grid indices using the actual data range.
    t_vals = [p[0] for p in pixels]
    a_vals = [p[1] for p in pixels]
    t_max     = max(t_vals)
    a_min     = min(a_vals)
    addr_span = max(a_vals) - a_min if max(a_vals) > a_min else 1.0

    grid = [[0.0] * s_cols for _ in range(t_rows)]
    for t_off, a_off, heat in pixels:
        t_idx = min(t_rows - 1, int(t_off / (t_max + 1e-9) * t_rows))
        s_idx = min(s_cols - 1, int((a_off - a_min) / (addr_span + 1e-9) * s_cols))
        grid[t_idx][s_idx] = max(grid[t_idx][s_idx], heat)
    return grid


# ── renderer ──────────────────────────────────────────────────────────────────

def render(grid, t_rows, s_cols, title, min_hz, max_hz):
    print(f'\n  {title}')
    for t in range(t_rows):
        row = '  '
        for s in range(s_cols):
            row += shade(grid[t][s], min_hz, max_hz)
        print(row)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} damon_data gt.log [time_rows] [space_cols] [damon_base] [damon_max] [damo_exe]')
        sys.exit(1)

    damon_path = sys.argv[1]
    gt_path    = sys.argv[2]
    damon_base = int(sys.argv[5]) if len(sys.argv) > 5 else None
    damon_max  = int(sys.argv[6]) if len(sys.argv) > 6 else None
    damo_exe   = sys.argv[7] if len(sys.argv) > 7 else 'damo'

    print(f'Loading GT: {gt_path}')
    regions_meta, entries = load_gt(gt_path)
    if not entries:
        print('Ground truth empty.'); sys.exit(1)
    print(f'  {len(entries)} accesses, {len(regions_meta)} region(s)')
    if damon_base is not None:
        print(f'  DAMON base: 0x{damon_base:x}')
    if damon_max is not None:
        print(f'  DAMON max:  0x{damon_max:x}')

    PAGE = 4096
    t0_ns = entries[0][0]
    t1_ns = entries[-1][0]
    dur_s = (t1_ns - t0_ns) / 1e9
    t_rows = int(sys.argv[3]) if len(sys.argv) > 3 else max(1, int(dur_s))
    s_cols_arg = int(sys.argv[4]) if len(sys.argv) > 4 else None

    if damon_base is not None and damon_max is not None:
        print(f'  DAMON span: {damon_max - damon_base} B')

    for ridx, meta in enumerate(regions_meta):
        if meta is None:
            continue
        base, n_pages = meta
        s_cols = s_cols_arg if s_cols_arg is not None else n_pages

        print(f'\n{"═"*55}')
        print(f'  Region {ridx}  base=0x{base:x}  {n_pages} pages  '
              f'resol={t_rows}×{s_cols}')
        print(f'{"═"*55}')

        gt_grid = build_gt_grid(entries, ridx, n_pages,
                                t_rows, s_cols, t0_ns, t1_ns)

        addr_start = base                  if damon_base is not None else None
        addr_end   = base + n_pages * PAGE if damon_base is not None else None
        rng = f'--address_range {addr_start} {addr_end}' if addr_start else ''
        print(f'  Running: {damo_exe} report heatmap --resol {t_rows} {s_cols} {rng} --output raw')
        damon_grid = build_damon_grid(damon_path, t_rows, s_cols, addr_start, addr_end, damo_exe)

        all_gt    = [v for row in gt_grid    for v in row]
        all_damon = [v for row in damon_grid for v in row] if damon_grid else []
        all_vals  = all_gt + all_damon
        has_zero  = any(v == 0.0 for v in all_vals)
        nonzero   = [v for v in all_vals if v > 0]
        min_hz = 0.0 if has_zero else (min(nonzero) if nonzero else 0.0)
        max_hz = max(nonzero) if nonzero else 1.0

        print(f'\n  scale: 0={min_hz:.1f} Hz  ...  9={max_hz:.1f} Hz')
        render(gt_grid, t_rows, s_cols, 'GT   — what actually happened', min_hz, max_hz)
        if damon_grid:
            render(damon_grid, t_rows, s_cols, 'DAMON — what kernel observed', min_hz, max_hz)
        else:
            print('\n  DAMON data unavailable or empty.')

        col_labels = [f'p{int(s * n_pages / s_cols)}' for s in range(s_cols)]
        print(f'\n  {"col":>5}  {"GT Hz":>8}  {"DAMON Hz":>9}  ratio  bar')
        print('  ' + '─' * 50)
        for s in range(s_cols):
            gt_avg   = sum(gt_grid[t][s] for t in range(t_rows)) / t_rows
            dmon_avg = sum(damon_grid[t][s] for t in range(t_rows)) / t_rows \
                       if damon_grid else 0.0
            ratio   = dmon_avg / gt_avg if gt_avg > 0 else float('nan')
            ratio_s = f'{ratio:.2f}' if not math.isnan(ratio) else '   —'
            bar     = '█' * min(20, int(ratio * 20)) if not math.isnan(ratio) else ''
            print(f'  {col_labels[s]:>5}  {gt_avg:>8.1f}  {dmon_avg:>9.1f}  '
                  f'{ratio_s}  {bar}')

    print()


if __name__ == '__main__':
    main()
