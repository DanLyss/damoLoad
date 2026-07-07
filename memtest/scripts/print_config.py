#!/usr/bin/env python3
"""Print a human-readable summary of a memtest workload JSON config."""
import json, sys

if len(sys.argv) < 2:
    print(f'Usage: {sys.argv[0]} workload.json', file=sys.stderr)
    sys.exit(1)

d = json.load(open(sys.argv[1]))

dur    = d.get('duration_sec', '?')
regions = d.get('regions', [])
tracks  = d.get('tracks',  [])
t_rows  = d.get('heatmap_time_rows',  'auto')
s_cols  = d.get('heatmap_space_cols', 'auto')

print(f'  duration  : {dur}s')
print(f'  heatmap   : {t_rows} rows × {s_cols} cols')
print()

print(f'  regions ({len(regions)}):')
for i, r in enumerate(regions):
    pages = r.get('pages', 10)
    print(f'    [{i}]  {pages} pages  ({pages*4} KB)')

print()
print(f'  tracks ({len(tracks)}):')
for i, t in enumerate(tracks):
    ridx  = t.get('region', 0)
    t0    = t.get('start_sec', 0)
    t1    = t.get('end_sec', dur)
    sp    = t.get('spatial',  {})
    tp    = t.get('temporal', {})
    stype = sp.get('type', '?')
    ttype = tp.get('type', '?')

    if stype == 'hotspot':
        hp    = sp.get('hot_pages', [])
        ratio = sp.get('hot_ratio', 0.8)
        s_detail = f'hotspot  pages={hp}  hot_ratio={ratio}'
    elif stype == 'zipf':
        s_detail = f'zipf  s={sp.get("s", 1.0)}'
    elif stype == 'gaussian':
        s_detail = f'gaussian  center={sp.get("center")}  sigma={sp.get("sigma")}'
    else:
        s_detail = stype

    if ttype == 'const':
        t_detail = f'const  {tp.get("hz", 100)} Hz'
    elif ttype == 'sine':
        t_detail = f'sine  {tp.get("base_hz")}±{tp.get("amplitude")} Hz  T={tp.get("period_sec")}s  φ={tp.get("phase_rad", 0)}'
    elif ttype == 'square':
        t_detail = f'square  {tp.get("on_hz")} Hz  duty={tp.get("duty")}  T={tp.get("period_sec")}s  φ={tp.get("phase_rad", 0)}'
    elif ttype == 'ramp':
        t_detail = f'ramp  {tp.get("start_hz")}→{tp.get("end_hz")} Hz'
    elif ttype == 'steps':
        steps = tp.get('steps', [])
        t_detail = 'steps  ' + '  '.join(f'{s["hz"]}Hz/{s["duration_sec"]}s' for s in steps)
    else:
        t_detail = ttype

    print(f'    [{i}]  region={ridx}  [{t0}s – {t1}s]')
    print(f'         spatial  : {s_detail}')
    print(f'         temporal : {t_detail}')
