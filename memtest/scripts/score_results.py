#!/usr/bin/env python3
"""Score memtest results (GT-vs-DAMON heatmap columns) with a robust metric.

Parses the "col  GT Hz  DAMON Hz  ratio  bar" tables out of every
rep*.log under a results directory, and scores each (GT, DAMON) column
pair with a bounded, regularized symmetric error:

    err = |GT - DAMON| / (GT + DAMON + EPS)

This stays in [0, 1) instead of blowing up when GT is near zero (which a
plain MAPE/ratio would do -- exactly the 47x/83x ratio outliers we saw on
cold columns). EPS (in Hz) is the only knob; it softens the near-zero
denominator without needing a separate outlier-clipping step.

Also reports Pearson correlation between GT and DAMON vectors per test,
as a scale-independent "did it find the right hot/cold shape" signal.

Standalone / portable: stdlib only, no repo dependency. Copy this one file
anywhere. Accepts any mix of files and/or directories; directories are
walked recursively and every regular file found is tried as a log (files
with no matching "p<N> <GT> <DAMON> <ratio>" rows are silently skipped, so
pointing it at a messy folder is safe). Results are grouped by each file's
immediate parent directory name (matching the "<config>/repN.log" layout
this was originally built for) -- if you just pass loose files with no
such grouping folder, each file's parent dir name is still used as its
group, which usually still does something sensible.

Usage:
    python3 score_results.py <path> [<path> ...] [--eps 1.0] [--exclude NAME ...]

    <path> can be a results directory (like our memtest/results_spatial_weighted),
    a single config subfolder, or individual log files.
"""
import argparse
import os
import re
import statistics as stats

ROW_RE = re.compile(r'^\s*p\d+\s+([\d.]+)\s+([\d.]+)\s+[\d.]+\s+')


def parse_file(path):
    pairs = []
    with open(path, 'r', errors='replace') as f:
        for line in f:
            m = ROW_RE.match(line)
            if m:
                gt = float(m.group(1))
                damon = float(m.group(2))
                pairs.append((gt, damon))
    return pairs


def regularized_error(pairs, eps):
    errs = [abs(g - d) / (g + d + eps) for g, d in pairs]
    return stats.mean(errs) if errs else None


def pearson(pairs):
    if len(pairs) < 2:
        return None
    gs = [g for g, d in pairs]
    ds = [d for g, d in pairs]
    mg, md = stats.mean(gs), stats.mean(ds)
    num = sum((g - mg) * (d - md) for g, d in pairs)
    dg = sum((g - mg) ** 2 for g in gs) ** 0.5
    dd = sum((d - md) ** 2 for d in ds) ** 0.5
    if dg == 0 or dd == 0:
        return None
    return num / (dg * dd)


def collect_files(paths):
    """Expand a mix of files/dirs into a flat list of regular files."""
    files = []
    for p in paths:
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root, _dirs, names in os.walk(p):
                for name in names:
                    files.append(os.path.join(root, name))
        else:
            print(f"warning: path not found, skipping: {p}")
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('paths', nargs='+',
                     help='results dir(s), config subfolder(s), or individual log file(s)')
    ap.add_argument('--eps', type=float, default=1.0,
                     help='Hz regularization constant (default 1.0)')
    ap.add_argument('--exclude', nargs='*', default=[],
                     help='group (parent dir) name(s) to skip (e.g. known-broken configs)')
    args = ap.parse_args()

    by_group = {}
    for f in collect_files(args.paths):
        group = os.path.basename(os.path.dirname(os.path.abspath(f))) or f
        if group in args.exclude:
            continue
        by_group.setdefault(group, []).append(f)

    rows = []
    for cfg, files in sorted(by_group.items()):
        rep_errs, rep_corrs, n_cols = [], [], []
        for rep_file in sorted(files):
            pairs = parse_file(rep_file)
            if not pairs:
                continue
            e = regularized_error(pairs, args.eps)
            c = pearson(pairs)
            if e is not None:
                rep_errs.append(e)
            if c is not None:
                rep_corrs.append(c)
            n_cols.append(len(pairs))
        if not rep_errs:
            continue
        rows.append({
            'config': cfg,
            'n_reps': len(rep_errs),
            'mean_err': stats.mean(rep_errs),
            'std_err': stats.pstdev(rep_errs) if len(rep_errs) > 1 else 0.0,
            'mean_corr': stats.mean(rep_corrs) if rep_corrs else float('nan'),
        })

    rows.sort(key=lambda r: r['mean_err'])

    print(f"{'config':<32} {'reps':>4} {'accuracy':>9} {'±std':>7} {'corr':>6}")
    print('-' * 62)
    for r in rows:
        acc = 1 - r['mean_err']
        print(f"{r['config']:<32} {r['n_reps']:>4} {acc:>9.3f} "
              f"{r['std_err']:>7.3f} {r['mean_corr']:>6.2f}")

    if rows:
        overall_acc = stats.mean(1 - r['mean_err'] for r in rows)
        overall_corr = stats.mean(
            r['mean_corr'] for r in rows if r['mean_corr'] == r['mean_corr'])
        print('-' * 62)
        print(f"{'OVERALL (' + str(len(rows)) + ' configs)':<32} "
              f"{'':>4} {overall_acc:>9.3f} {'':>7} {overall_corr:>6.2f}")

        print("\nWorst 5 (lowest accuracy):")
        for r in rows[-5:][::-1]:
            print(f"  {r['config']:<32} accuracy={1-r['mean_err']:.3f}  "
                  f"corr={r['mean_corr']:.2f}")

        print("\nBest 5 (highest accuracy):")
        for r in rows[:5]:
            print(f"  {r['config']:<32} accuracy={1-r['mean_err']:.3f}  "
                  f"corr={r['mean_corr']:.2f}")


if __name__ == '__main__':
    main()
