#!/usr/bin/env python3
"""
Build a kdamonds JSON config for damo record.

Usage: build_kdamonds.py <pid> <regions_file> <damo_path>

  pid           — PID of the target process
  regions_file  — path to a file with one DEC_START:DEC_END per line
  damo_path     — path to the damo executable

Prints the kdamonds JSON to stdout, exits non-zero on failure.

Why not just pass all -r flags to damo?
  damo args damon -r r1 -r r2 ... --target_pid PID creates one DAMON target
  per -r flag; only the first target gets the PID. We work around this by
  asking damo for a single-region template, then patching all regions in.
  DAMON sysfs also requires regions sorted by ascending start address.
"""
import subprocess, json, sys

if len(sys.argv) != 4:
    print(f'Usage: {sys.argv[0]} <pid> <regions_file> <damo_path>', file=sys.stderr)
    sys.exit(1)

pid          = sys.argv[1]
regions_file = sys.argv[2]
damo         = sys.argv[3]

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
regions.sort(key=lambda r: int(r['start']))  # DAMON requires ascending order
template['kdamonds'][0]['contexts'][0]['targets'][0]['regions'] = regions
print(json.dumps(template))
