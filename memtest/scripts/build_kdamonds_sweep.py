#!/usr/bin/env python3
"""
Build a multi-kdamond JSON config for damo record — one kdamond per
(min_nr_regions, max_nr_regions) sweep point, all monitoring the same
target process/regions simultaneously.

Usage: build_kdamonds_sweep.py <pid> <regions_file> <damo_path> <min1> <max1> [<min2> <max2> ...]

  pid           — PID of the target process
  regions_file  — path to a file with one DEC_START:DEC_END per line
  damo_path     — path to the damo executable
  <minN> <maxN> — nr_regions bounds for sweep point N

Prints the kdamonds JSON to stdout, exits non-zero on failure.

Reuses build_kdamonds.py's approach: ask damo for a single-region template
(one subprocess call, so every sweep point shares identical monitoring
intervals — damo_record.py only reads kdamonds[0]'s intervals for display
purposes, so keeping intervals identical across all kdamonds sidesteps that
limitation entirely), then patch in the full region list and each sweep
point's nr_regions bounds.
"""
import subprocess, json, sys, copy

args = sys.argv[1:]
if len(args) < 5 or len(args) % 2 != 1:
    print(f'Usage: {sys.argv[0]} <pid> <regions_file> <damo_path> <min1> <max1> [<min2> <max2> ...]',
          file=sys.stderr)
    sys.exit(1)

pid, regions_file, damo = args[0], args[1], args[2]
sweep_args = args[3:]
sweep_points = [(sweep_args[i], sweep_args[i + 1]) for i in range(0, len(sweep_args), 2)]

regions = []
with open(regions_file) as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        s, e = line.split(':')
        regions.append({'start': s, 'end': e})

if not regions:
    print('ERROR: no regions in regions_file', file=sys.stderr)
    sys.exit(1)

regions.sort(key=lambda r: int(r['start']))  # DAMON requires ascending order
first = regions[0]

r = subprocess.run(
    [damo, 'args', 'damon',
     '--ops', 'fvaddr', '--target_pid', pid,
     '-r', first['start'] + '-' + first['end'],
     '--monitoring_intervals', '5ms', '100ms', '1s',
     '--format', 'json'],
    capture_output=True, text=True)

if r.returncode != 0:
    print(f'ERROR: damo args damon failed:\n{r.stderr}', file=sys.stderr)
    sys.exit(1)

template = json.loads(r.stdout)
base_kdamond = template['kdamonds'][0]
base_kdamond['contexts'][0]['targets'][0]['regions'] = regions

kdamonds = []
for min_r, max_r in sweep_points:
    kd = copy.deepcopy(base_kdamond)
    kd['contexts'][0]['nr_regions'] = {'min': str(min_r), 'max': str(max_r)}
    kdamonds.append(kd)

print(json.dumps({'kdamonds': kdamonds}))
