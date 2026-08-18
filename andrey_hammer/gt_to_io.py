#!/usr/bin/env python3
"""
gt_to_io.py — converts andrey_hammer's own ground truth (gt.log + gt.log.frames)
into an io-format text file, WITHOUT going through DAMON at all.

Why: DAMON only samples one page per region every 5ms (capped at 200Hz,
lossy by construction — see the main README's "Key DAMON Behaviors"
section). `damo report access --raw` on a live recording therefore reflects
DAMON's *observation* of andrey_hammer, not what andrey_hammer actually did.
This script builds the io-format file straight from andrey_hammer's own
exact record instead, so `compare_io.py` can answer a different question:
not "did DAMON see it," but "did andrey_hammer's replay itself match the
original passport's model" — isolating replay fidelity from DAMON's own
measurement noise.

Bins touches into the SAME spatial bins (matrix_geometry.cols, same
page-aligned boundary formula) and the SAME per-frame merge/age convention
as format_raw.py, so the output is directly comparable to sim_raw3.txt-style
files with `compare_io.py` (or by eye).

Usage:
    python3 gt_to_io.py --gt gt.log --frames gt.log.frames --meta meta.json \
        --output gt_as_io.txt [--merge-tolerance 0.5]
"""
import argparse
import json


def format_length(size_bytes):
    if size_bytes >= 1024**4:
        return f"{size_bytes / 1024**4:8.3f} TiB"
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:8.3f} GiB"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:8.3f} MiB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:8.3f} KiB"
    return f"{size_bytes:8d} B"


def get_address_span(meta):
    phys = meta.get('physical_bounds', {})
    geom = meta.get('matrix_geometry', {})
    start_raw = phys.get('active_min_addr') or meta.get('start_addr') or geom.get('start_addr')
    end_raw = phys.get('active_max_addr') or meta.get('end_addr') or geom.get('end_addr')
    if start_raw is None or end_raw is None:
        raise KeyError("meta.json missing address bounds (physical_bounds.active_min_addr/active_max_addr or start_addr/end_addr)")
    start = int(str(start_raw), 0) if isinstance(start_raw, str) else int(start_raw)
    end = int(str(end_raw), 0) if isinstance(end_raw, str) else int(end_raw)
    PAGE = 4096
    start = (start // PAGE) * PAGE
    end = ((end + PAGE - 1) // PAGE) * PAGE
    return end - start


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--gt', required=True, help='path to gt.log (ts_ns region page)')
    ap.add_argument('--frames', required=True, help='path to gt.log.frames (frame_idx start_ns end_ns nominal_dt_ms)')
    ap.add_argument('--meta', required=True, help='path to meta.json (for matrix_geometry.cols + address span)')
    ap.add_argument('--output', required=True, help='output io-format text path')
    ap.add_argument('--merge-tolerance', type=float, default=0.5,
                     help='nr_accesses difference threshold for merging adjacent bins (default: 0.5, matches format_raw.py)')
    args = ap.parse_args()

    meta = json.load(open(args.meta))
    cols = meta['matrix_geometry']['cols']
    total_bytes = get_address_span(meta)

    PAGE = 4096
    bin_bounds = [round((c * total_bytes / cols) / PAGE) * PAGE for c in range(cols + 1)]
    bin_bounds[0], bin_bounds[-1] = 0, total_bytes

    def page_to_bin(page_idx):
        addr = page_idx * PAGE
        # binary search would be nicer at scale; linear is fine for cols ~ hundreds
        for c in range(cols):
            if bin_bounds[c] <= addr < bin_bounds[c + 1]:
                return c
        return cols - 1

    frames = []
    with open(args.frames) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            idx, start_ns, end_ns, nominal_dt_ms = line.split()
            frames.append((int(idx), int(start_ns), int(end_ns), float(nominal_dt_ms)))

    # bucket touches into frames by real elapsed time window (not nominal)
    frame_bin_counts = [dict() for _ in frames]
    frame_ptr = 0
    with open(args.gt) as f:
        for line in f:
            if line.startswith('#') or not line.strip():
                continue
            ts_s, _region_s, page_s = line.split()
            ts, page = int(ts_s), int(page_s)
            while frame_ptr < len(frames) - 1 and ts >= frames[frame_ptr][2]:
                frame_ptr += 1
            b = page_to_bin(page)
            d = frame_bin_counts[frame_ptr]
            d[b] = d.get(b, 0) + 1

    prev_age = {}
    with open(args.output, 'w') as out:
        for (f_idx, start_ns, end_ns, nominal_dt_ms), counts in zip(frames, frame_bin_counts):
            row = [counts.get(c, 0) for c in range(cols)]

            merged = []
            curr_start, curr_acc = 0, row[0]
            for c in range(1, cols):
                if abs(row[c] - curr_acc) <= args.merge_tolerance:
                    continue
                merged.append((bin_bounds[curr_start], bin_bounds[c], curr_acc))
                curr_start, curr_acc = c, row[c]
            merged.append((bin_bounds[curr_start], bin_bounds[cols], curr_acc))

            cur_age = {}
            final = []
            for r_start, r_end, r_acc in merged:
                key = (r_start, r_end)
                age = prev_age.get(key, 0) + 1
                cur_age[key] = age
                final.append((r_start, r_end, r_acc, age))
            prev_age = cur_age

            dur_ms = (end_ns - start_ns) / 1e6
            out.write(f"monitoring_start:    {start_ns / 1e6:16.3f} ms\n")
            out.write(f"monitoring_end:      {end_ns / 1e6:16.3f} ms\n")
            out.write(f"monitoring_duration: {dur_ms:16.3f} ms\n")
            out.write("target_id: 0\n")
            out.write(f"nr_regions: {len(final)}\n")
            out.write("# start_addr     end_addr        length  nr_accesses   age\n")
            for r_start, r_end, r_acc, r_age in final:
                out.write(f"{r_start:x}-{r_end:x} ({format_length(r_end - r_start)}) {r_acc:>11} {r_age:>5}\n")
            out.write("\n")

    print(f"[OK] {len(frames)} frames converted from ground truth (no DAMON involved).")
    print(f"[INFO] Output: {args.output}")


if __name__ == '__main__':
    main()
