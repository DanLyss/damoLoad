#!/usr/bin/env python3
"""Generate a large, realistic-heavyweight-app-scale workload for the
min_nr_regions/max_nr_regions sensitivity sweep (see
memtest/scripts/run_nr_regions_sweep.sh).

~5500 regions, skewed hot/warm/cold access-rate tiers (mimicking a real
process's memory map: a small hot working set, a larger warm set, and a
long tail of mostly-cold mappings), with a shared 4-phase step envelope so
the aggregate access-rate signal has a visible, checkable trend shape.
"""
import json, os, random

OUT = os.path.join(os.path.dirname(__file__), '..', 'configs')
os.makedirs(OUT, exist_ok=True)

random.seed(2024)

N_REGIONS = 5500
DURATION_SEC = 60
PHASE_SEC = 15  # 4 phases * 15s = 60s
ENVELOPE = [1.0, 0.4, 1.3, 0.7]

PAGE_CHOICES = [4, 8, 16, 32, 64, 128, 256]
PAGE_WEIGHTS = [35, 25, 20, 10, 6, 3, 1]

N_HOT  = round(N_REGIONS * 0.05)
N_WARM = round(N_REGIONS * 0.20)
# remainder is cold


def uniform():
    return {'type': 'uniform'}


def hotspot(pages, ratio):
    return {'type': 'hotspot', 'hot_pages': pages, 'hot_ratio': ratio}


def steps(*pairs):
    return {'type': 'steps', 'steps': [{'hz': h, 'duration_sec': d} for h, d in pairs]}


def track(region, sp, tp):
    return {'region': region, 'spatial': sp, 'temporal': tp, 'start_sec': 0, 'end_sec': DURATION_SEC}


regions = [{'pages': random.choices(PAGE_CHOICES, weights=PAGE_WEIGHTS)[0]}
           for _ in range(N_REGIONS)]

tracks = []
projected_entries = 0.0
avg_envelope = sum(ENVELOPE) / len(ENVELOPE)

for i in range(N_REGIONS):
    if i < N_HOT:
        base_hz = random.uniform(80, 250)
        spatial = hotspot([0, 1], 0.85)
    elif i < N_HOT + N_WARM:
        base_hz = random.uniform(10, 60)
        spatial = hotspot([0, 1], 0.85)
    else:
        base_hz = random.uniform(0.5, 5)
        spatial = uniform()

    temporal = steps(*[(round(base_hz * m, 2), PHASE_SEC) for m in ENVELOPE])
    tracks.append(track(i, spatial, temporal))
    projected_entries += base_hz * avg_envelope * DURATION_SEC

config = {
    'duration_sec': DURATION_SEC,
    'regions': regions,
    'tracks': tracks,
}

path = os.path.join(OUT, '101_5500reg_realistic_app.json')
with open(path, 'w') as f:
    json.dump(config, f, indent=2)

GT_LOG_CAPACITY = 10 * 1024 * 1024
print(f'Regions: {N_REGIONS}  (hot={N_HOT} warm={N_WARM} cold={N_REGIONS - N_HOT - N_WARM})')
print(f'Duration: {DURATION_SEC}s across {len(ENVELOPE)} phases of {PHASE_SEC}s each')
print(f'Projected GT log entries: ~{int(projected_entries):,} '
      f'(cap is {GT_LOG_CAPACITY:,})')
if projected_entries > 0.8 * GT_LOG_CAPACITY:
    print('WARNING: projected entries exceed 80% of gt_log capacity — '
          'lower duration_sec or access rates before running.')
print(f'Wrote {path}')
