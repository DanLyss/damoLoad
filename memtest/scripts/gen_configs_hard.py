#!/usr/bin/env python3
"""Generate 50 hard workload configs (#51-100): 100+ regions, complex patterns."""
import json, os, math, random

OUT = os.path.join(os.path.dirname(__file__), '..', 'configs')
os.makedirs(OUT, exist_ok=True)

configs = []

def cfg(name, duration, regions, tracks, t_rows=None, s_cols=None):
    d = {
        'duration_sec': duration,
        'heatmap_time_rows':  t_rows or duration,
        'heatmap_space_cols': s_cols or regions[0]['pages'],
        'regions': regions,
        'tracks':  tracks,
    }
    configs.append((name, d))

# ── temporal helpers ──────────────────────────────────────────────────────────
def sine(base, amp, period, phase=0):
    return {'type':'sine','base_hz':base,'amplitude':amp,'period_sec':period,'phase_rad':phase}
def sq(on_hz, duty, period, phase=0):
    return {'type':'square','on_hz':on_hz,'duty':duty,'period_sec':period,'phase_rad':phase}
def const(hz):
    return {'type':'const','hz':hz}
def ramp(s, e):
    return {'type':'ramp','start_hz':s,'end_hz':e}
def steps(*pairs):
    return {'type':'steps','steps':[{'hz':h,'duration_sec':d} for h,d in pairs]}

# ── spatial helpers ───────────────────────────────────────────────────────────
def uniform():
    return {'type':'uniform'}
def hotspot(pages, ratio):
    return {'type':'hotspot','hot_pages':pages,'hot_ratio':ratio}
def zipf(s):
    return {'type':'zipf','s':s}
def gauss(center, sigma):
    return {'type':'gaussian','center':center,'sigma':sigma}
def seq():
    return {'type':'sequential'}
def all_pages():
    return {'type':'all'}

def track(region, sp, tp, t0=0, t1=None):
    return {'region':region,'spatial':sp,'temporal':tp,'start_sec':t0,'end_sec':t1}

# ── region helpers ────────────────────────────────────────────────────────────
def regs(n, pages=10):
    """n identical regions each with `pages` pages."""
    return [{'pages': pages}] * n

def regs_var(sizes):
    """regions with varying page counts."""
    return [{'pages': p} for p in sizes]

# ─────────────────────────────────────────────────────────────────────────────
# 51-60: 100 identical regions, one track per region, simple patterns
# ─────────────────────────────────────────────────────────────────────────────

# 51: 100 regions, uniform + const
N = 100
cfg('51_100reg_uniform_const',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), const(100), t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# 52: 100 regions, sine with round-robin phase
N = 100
cfg('52_100reg_sine_phase_sweep',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), sine(80, 60, 4.0, i * 2*math.pi / N), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 53: 100 regions, square wave alternating odd/even anti-phase
N = 100
cfg('53_100reg_square_antiphase',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), sq(200, 0.4, 2.0, 0 if i % 2 == 0 else math.pi), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 54: 100 regions, first 50 ramp up / last 50 ramp down
N = 100
cfg('54_100reg_ramp_split',
    duration=30, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), ramp(0, 200) if i < N//2 else ramp(200, 0), t1=30)
        for i in range(N)
    ], t_rows=30, s_cols=10)

# 55: 100 regions, zipf with skew gradient
N = 100
cfg('55_100reg_zipf_gradient',
    duration=20, regions=regs(N, pages=20),
    tracks=[
        track(i, zipf(0.5 + i * 2.0 / N), const(100), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=20)

# 56: 100 regions, cascading activation (0.3s apart)
N = 100
cfg('56_100reg_cascade',
    duration=40, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), const(150), t0=round(i * 0.3, 1), t1=40)
        for i in range(N)
    ], t_rows=40, s_cols=10)

# 57: 100 regions, cascading deactivation
N = 100
cfg('57_100reg_cascade_off',
    duration=40, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), const(150), t0=0, t1=round(40 - i * 0.3, 1))
        for i in range(N)
    ], t_rows=40, s_cols=10)

# 58: 100 regions, hotspot with ratio gradient
N = 100
cfg('58_100reg_hotspot_ratio_gradient',
    duration=20, regions=regs(N, pages=20),
    tracks=[
        track(i, hotspot([0, 1], round(0.5 + i * 0.4 / N, 3)), const(120), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=20)

# 59: 100 regions, 4 cyclic step sequences
N = 100
STEP_SEQS = [
    steps((200, 5), (50, 5), (100, 5), (20, 5)),
    steps((50, 5), (200, 5), (20, 5), (100, 5)),
    steps((100, 5), (20, 5), (200, 5), (50, 5)),
    steps((20, 5), (100, 5), (50, 5), (200, 5)),
]
cfg('59_100reg_steps_4phase',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), STEP_SEQS[i % 4], t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# 60: 100 regions, Gaussian spatial with varying center
N = 100
cfg('60_100reg_gauss_centers',
    duration=20, regions=regs(N, pages=20),
    tracks=[
        track(i, gauss(round(i * 20.0 / N, 1), 2.0), const(120), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=20)

# ─────────────────────────────────────────────────────────────────────────────
# 61-70: 100+ regions with multi-track patterns
# ─────────────────────────────────────────────────────────────────────────────

# 61: 100 regions in 10 groups, each group shares a sine phase
N = 100
GROUPS = 10
cfg('61_100reg_10groups_sine',
    duration=20, regions=regs(N, pages=15),
    tracks=[
        track(i, uniform(),
              sine(80, 60, 3.0, (i // (N // GROUPS)) * 2*math.pi / GROUPS),
              t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=15)

# 62: 100 regions, first 50 then second 50 activate
N = 100
cfg('62_100reg_half_half_swap',
    duration=30, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), const(180), t0=0,  t1=15) for i in range(50)] +
        [track(i, uniform(), const(180), t0=15, t1=30) for i in range(50, 100)]
    ), t_rows=30, s_cols=10)

# 63: 120 regions, alternating hotspot/uniform
N = 120
cfg('63_120reg_alternating_spatial',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, hotspot([0, 1], 0.9) if i % 2 == 0 else uniform(), const(150), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 64: 100 regions, each with 2 tracks (hot core + cold background)
N = 100
cfg('64_100reg_2tracks_each',
    duration=20, regions=regs(N, pages=20),
    tracks=(
        [track(i, hotspot([0, 1, 2], 0.9), const(150), t1=20) for i in range(N)] +
        [track(i, uniform(),              const(10),  t1=20) for i in range(N)]
    ), t_rows=20, s_cols=20)

# 65: 100 regions, sine + square superposition
N = 100
cfg('65_100reg_sine_plus_square',
    duration=20, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), sine(60, 40, 3.0, i * 2*math.pi / N), t1=20) for i in range(N)] +
        [track(i, hotspot([0], 0.8), sq(80, 0.3, 1.5, i * math.pi / N), t1=20) for i in range(N)]
    ), t_rows=20, s_cols=10)

# 66: 150 regions, varying page counts 10-30
PAGES_LIST = [10 + (i % 21) for i in range(150)]
cfg('66_150reg_varying_sizes',
    duration=20, regions=regs_var(PAGES_LIST),
    tracks=[track(i, uniform(), const(100), t1=20) for i in range(150)],
    t_rows=20, s_cols=10)

# 67: 100 regions, 5 duty cycles for burst visibility sweep
N = 100
DUTIES = [0.01, 0.05, 0.1, 0.25, 0.5]
cfg('67_100reg_burst_duty_sweep',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), sq(200, DUTIES[i % len(DUTIES)], 1.0), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 68: 100 regions, competing zipf (2 tracks each)
N = 100
cfg('68_100reg_competing_zipf',
    duration=20, regions=regs(N, pages=15),
    tracks=(
        [track(i, zipf(1.5), const(100), t1=20) for i in range(N)] +
        [track(i, zipf(2.0), const(80),  t1=20) for i in range(N)]
    ), t_rows=20, s_cols=15)

# 69: 100 regions, sequential scan + hotspot burst
N = 100
cfg('69_100reg_seq_plus_burst',
    duration=20, regions=regs(N, pages=15),
    tracks=(
        [track(i, seq(), const(80), t1=20) for i in range(N)] +
        [track(i, hotspot([0, 1, 2], 0.9), sq(200, 0.1, 2.0), t1=20) for i in range(N)]
    ), t_rows=20, s_cols=15)

# 70: 200 regions, very light access (cold region merge stress)
N = 200
cfg('70_200reg_cold_stress',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), const(5), t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# ─────────────────────────────────────────────────────────────────────────────
# 71-80: complex mixed patterns, 100+ regions
# ─────────────────────────────────────────────────────────────────────────────

# 71: 100 regions, 3 groups: hot/warm/cold
N = 100
cfg('71_100reg_hot_warm_cold',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(),
              const(200 if i < 33 else (80 if i < 67 else 5)),
              t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 72: 100 regions, sine frequency gradient (slow → fast)
N = 100
cfg('72_100reg_sine_freq_gradient',
    duration=30, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), sine(60, 50, round(0.5 + i * 9.5 / N, 2)), t1=30)
        for i in range(N)
    ], t_rows=30, s_cols=10)

# 73: 100 regions, random activation windows within 30s
random.seed(42)
N = 100
dur = 30
_w = [(round(random.uniform(0, dur*0.7), 1),
       round(random.uniform(dur*0.3, dur), 1)) for _ in range(N)]
_w = [(a, max(round(a + 2, 1), b)) for a, b in _w]
cfg('73_100reg_random_windows',
    duration=dur, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), const(150), t0=_w[i][0], t1=_w[i][1]) for i in range(N)],
    t_rows=30, s_cols=10)

# 74: 100 regions, ramp with staggered start (wave effect)
N = 100
cfg('74_100reg_ramp_wave',
    duration=40, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), ramp(0, 200), t0=round(i * 0.3, 1), t1=40)
        for i in range(N)
    ], t_rows=40, s_cols=10)

# 75: 110 regions, 10 zipf skew values × 11 regions each
N = 110
SKEWS = [0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 4.0]
cfg('75_110reg_zipf_all_skews',
    duration=20, regions=regs(N, pages=20),
    tracks=[
        track(i, zipf(SKEWS[i % len(SKEWS)]), const(120), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=20)

# 76: 100 regions, tournament-style even/odd swap every 10s
N = 100
cfg('76_100reg_tournament_swap',
    duration=40, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), steps((200, 10), (10, 10), (200, 10), (10, 10)), t1=40)
         for i in range(0, N, 2)] +
        [track(i, uniform(), steps((10, 10), (200, 10), (10, 10), (200, 10)), t1=40)
         for i in range(1, N, 2)]
    ), t_rows=40, s_cols=10)

# 77: 100 regions, all_pages burst with spread phase
N = 100
cfg('77_100reg_all_pages_burst',
    duration=20, regions=regs(N, pages=5),
    tracks=[
        track(i, all_pages(), sq(50, 0.3, 3.0, i * 2*math.pi / N), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=5)

# 78: 100 regions, 5 temporal groups cycling
N = 100
TGROUPS = [
    const(200),
    sine(80, 70, 3.0),
    sq(200, 0.25, 2.0),
    ramp(0, 200),
    steps((50, 4), (200, 4), (10, 4), (150, 4), (80, 4)),
]
cfg('78_100reg_5temporal_groups',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), TGROUPS[i % len(TGROUPS)], t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# 79: 100 regions, Gaussian center shifts mid-run
N = 100
cfg('79_100reg_gauss_shift',
    duration=30, regions=regs(N, pages=20),
    tracks=(
        [track(i, gauss(5, 2), const(120), t0=0,  t1=15) for i in range(N)] +
        [track(i, gauss(15, 2), const(120), t0=15, t1=30) for i in range(N)]
    ), t_rows=30, s_cols=20)

# 80: 100 regions, 3-layer: cold background + sine mid + hotspot burst
N = 100
cfg('80_100reg_3layer',
    duration=20, regions=regs(N, pages=15),
    tracks=(
        [track(i, uniform(), const(10), t1=20) for i in range(N)] +
        [track(i, gauss(7, 3), sine(60, 50, 4.0, i * 0.063), t1=20) for i in range(N)] +
        [track(i, hotspot([0, 1], 0.9), sq(200, 0.1, 1.0), t1=20) for i in range(N)]
    ), t_rows=20, s_cols=15)

# ─────────────────────────────────────────────────────────────────────────────
# 81-90: stress tests — DAMON limits, realistic loads
# ─────────────────────────────────────────────────────────────────────────────

# 81: 100 regions, alternating uniform→hotspot (split/merge trigger cycle)
N = 100
cfg('81_100reg_split_merge_stress',
    duration=40, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(),           const(150), t0=0,  t1=10) for i in range(N)] +
        [track(i, hotspot([0, 1], 0.95), const(150), t0=10, t1=20) for i in range(N)] +
        [track(i, uniform(),           const(150), t0=20, t1=30) for i in range(N)] +
        [track(i, hotspot([0, 1], 0.95), const(150), t0=30, t1=40) for i in range(N)]
    ), t_rows=40, s_cols=10)

# 82: 100 regions, sub-aggr-interval bursts (should be invisible to DAMON)
N = 100
cfg('82_100reg_sub_aggr_bursts',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), sq(200, 0.005, 0.5), t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# 83: 100 regions, 5 duty cycle groups for burst visibility comparison
N = 100
DUTIES5 = [0.005, 0.01, 0.05, 0.1, 0.5]
cfg('83_100reg_burst_visibility',
    duration=20, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), sq(200, DUTIES5[i % 5], 1.0), t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 84: 100 regions, database simulation (index/data/log pattern)
N = 100  # 34 index + 33 data + 33 log ≈ 100
cfg('84_100reg_database_sim',
    duration=30,
    regions=regs_var([20 if i % 3 == 0 else (50 if i % 3 == 1 else 10)
                      for i in range(N)]),
    tracks=[
        track(i,
              zipf(2.5) if i % 3 == 0 else (zipf(1.0) if i % 3 == 1 else seq()),
              const(200 if i % 3 == 0 else (120 if i % 3 == 1 else 80)),
              t1=30)
        for i in range(N)
    ], t_rows=30, s_cols=20)

# 85: 100 regions, ML training (model shards / activations / gradients)
N = 100
cfg('85_100reg_ml_training_sim',
    duration=30, regions=regs(N, pages=15),
    tracks=(
        [track(i, seq(),             sine(80, 60, 6.0, i * 0.063), t1=30) for i in range(0, N, 3)] +
        [track(i, gauss(7, 3),       const(150),                   t1=30) for i in range(1, N, 3)] +
        [track(i, hotspot([0], 0.9), sq(200, 0.2, 1.0),            t1=30) for i in range(2, N, 3)]
    ), t_rows=30, s_cols=15)

# 86: 100 regions, frequency decay (200→5 in 6 steps)
N = 100
cfg('86_100reg_freq_decay',
    duration=30, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), steps((200, 5), (150, 5), (100, 5), (50, 5), (20, 5), (5, 5)), t1=30)
        for i in range(N)
    ], t_rows=30, s_cols=10)

# 87: 100 regions, frequency growth (5→200 in 6 steps)
N = 100
cfg('87_100reg_freq_growth',
    duration=30, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), steps((5, 5), (20, 5), (50, 5), (100, 5), (150, 5), (200, 5)), t1=30)
        for i in range(N)
    ], t_rows=30, s_cols=10)

# 88: 100 regions, dominance swap: even/odd alternate every 5s
N = 100
dur = 30
_on_even  = steps(*[(200 if (t // 5) % 2 == 0 else 5, 5) for t in range(0, dur, 5)])
_on_odd   = steps(*[(5 if (t // 5) % 2 == 0 else 200, 5) for t in range(0, dur, 5)])
cfg('88_100reg_dominance_swap',
    duration=dur, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), _on_even, t1=dur) for i in range(0, N, 2)] +
        [track(i, uniform(), _on_odd,  t1=dur) for i in range(1, N, 2)]
    ), t_rows=30, s_cols=10)

# 89: 200 regions, mixed random sizes and patterns
random.seed(7)
N = 200
_pages_89 = [random.choice([5, 8, 10, 12, 15, 20]) for _ in range(N)]
_SPATS_89 = [uniform(), zipf(1.2), gauss(5, 2), hotspot([0, 1], 0.85), seq()]
_TEMPS_89 = [const(120), sine(60, 50, 3.0), sq(150, 0.3, 2.0), ramp(0, 150), ramp(150, 0)]
cfg('89_200reg_mixed_random',
    duration=20, regions=regs_var(_pages_89),
    tracks=[
        track(i, _SPATS_89[random.randint(0, 4)], _TEMPS_89[random.randint(0, 4)], t1=20)
        for i in range(N)
    ], t_rows=20, s_cols=10)

# 90: 100 regions, ping-pong pairs (anti-phase square)
N = 100
cfg('90_100reg_pingpong_pairs',
    duration=20, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), sq(200, 0.5, 2.0, 0),        t1=20) for i in range(0, N, 2)] +
        [track(i, uniform(), sq(200, 0.5, 2.0, math.pi),  t1=20) for i in range(1, N, 2)]
    ), t_rows=20, s_cols=10)

# ─────────────────────────────────────────────────────────────────────────────
# 91-100: ultimate — 200-300 regions, long durations, max complexity
# ─────────────────────────────────────────────────────────────────────────────

# 91: 200 regions, 4-phase sine (quadrature)
N = 200
T4 = [sine(80, 70, 3.0, p) for p in [0, math.pi/2, math.pi, 3*math.pi/2]]
cfg('91_200reg_4phase_sine',
    duration=20, regions=regs(N, pages=10),
    tracks=[track(i, uniform(), T4[i % 4], t1=20) for i in range(N)],
    t_rows=20, s_cols=10)

# 92: 300 regions, const — maximum region count stress
N = 300
cfg('92_300reg_const_stress',
    duration=20, regions=regs(N, pages=5),
    tracks=[track(i, uniform(), const(80), t1=20) for i in range(N)],
    t_rows=20, s_cols=5)

# 93: 100 regions, 3 Gaussian hotspots per region
N = 100
cfg('93_100reg_3gauss_each',
    duration=20, regions=regs(N, pages=30),
    tracks=(
        [track(i, gauss(5,  2), const(150), t1=20) for i in range(N)] +
        [track(i, gauss(15, 2), const(100), t1=20) for i in range(N)] +
        [track(i, gauss(25, 2), const(50),  t1=20) for i in range(N)]
    ), t_rows=20, s_cols=30)

# 94: 100 regions, realistic micro-benchmark (code/heap/stack/cold)
N = 100
cfg('94_100reg_microbench',
    duration=30, regions=regs(N, pages=20),
    tracks=(
        [track(i, seq(),              const(150),         t1=30) for i in range(0, N, 4)] +
        [track(i, zipf(1.2),          sine(80, 60, 4.0),  t1=30) for i in range(1, N, 4)] +
        [track(i, hotspot([18, 19], 0.85), const(200),    t1=30) for i in range(2, N, 4)] +
        [track(i, uniform(),          const(3),           t1=30) for i in range(3, N, 4)]
    ), t_rows=30, s_cols=20)

# 95: 100 regions, multi-frequency interference (2 tracks at different freqs)
N = 100
FREQS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0]
cfg('95_100reg_multi_freq',
    duration=30, regions=regs(N, pages=10),
    tracks=(
        [track(i, uniform(), sine(60, 50, FREQS[i % len(FREQS)], 0), t1=30)
         for i in range(N)] +
        [track(i, hotspot([0, 1], 0.8),
               sq(120, 0.3, FREQS[(i + 5) % len(FREQS)]), t1=30)
         for i in range(N)]
    ), t_rows=30, s_cols=10)

# 96: 100 regions, 3 spatial patterns rotating every 10s
N = 100
cfg('96_100reg_3spatial_rotate',
    duration=30, regions=regs(N, pages=20),
    tracks=(
        [track(i, uniform(),           const(100), t0=0,  t1=10) for i in range(N)] +
        [track(i, hotspot([0, 1], 0.95), const(100), t0=10, t1=20) for i in range(N)] +
        [track(i, zipf(2.0),           const(100), t0=20, t1=30) for i in range(N)]
    ), t_rows=30, s_cols=20)

# 97: 150 regions, fire-and-forget (each active 1s, staggered across 30s)
N = 150
cfg('97_150reg_fire_and_forget',
    duration=30, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), const(200),
              t0=round(i * 30.0 / N, 2),
              t1=round(min(i * 30.0 / N + 1.0, 30.0), 2))
        for i in range(N)
    ], t_rows=30, s_cols=10)

# 98: 100 regions, working set expansion (regions join over 50s)
N = 100
cfg('98_100reg_working_set_expansion',
    duration=50, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), const(150), t0=round(i * 50.0 / N, 1), t1=50)
        for i in range(N)
    ], t_rows=50, s_cols=10)

# 99: 100 regions, working set contraction (regions leave over 50s)
N = 100
cfg('99_100reg_working_set_shrink',
    duration=50, regions=regs(N, pages=10),
    tracks=[
        track(i, uniform(), const(150), t0=0, t1=round(50.0 - i * 50.0 / N, 1))
        for i in range(N)
    ], t_rows=50, s_cols=10)

# 100: 100 regions — ultimate chaos: every region different size, spatial, temporal, window
N = 100
random.seed(99)
_SPATS_100 = [
    uniform(), zipf(0.8), zipf(1.5), zipf(2.5),
    gauss(3, 1), gauss(5, 2), gauss(8, 3),
    hotspot([0], 0.8), hotspot([0, 1], 0.9), hotspot([0, 1, 2], 0.7),
    seq(), all_pages(),
]
_TEMPS_100 = [
    const(20), const(80), const(150), const(200),
    sine(80, 70, 2.0), sine(60, 50, 5.0, math.pi),
    sq(200, 0.1, 1.0), sq(200, 0.5, 2.0),
    ramp(0, 200), ramp(200, 0),
    steps((50, 5), (200, 5)), steps((200, 5), (5, 5)),
]
_pages_100 = [random.choice([5, 8, 10, 12, 15, 20]) for _ in range(N)]
_t0_100 = [round(random.uniform(0, 15), 1) for _ in range(N)]
_t1_100 = [round(random.uniform(_t0_100[i] + 3, 30), 1) for i in range(N)]
cfg('100_ultimate_100reg_chaos',
    duration=30, regions=regs_var(_pages_100),
    tracks=[
        track(i,
              _SPATS_100[random.randint(0, len(_SPATS_100)-1)],
              _TEMPS_100[random.randint(0, len(_TEMPS_100)-1)],
              t0=_t0_100[i], t1=_t1_100[i])
        for i in range(N)
    ], t_rows=30, s_cols=10)

# ─────────────────────────────────────────────────────────────────────────────
# write files
# ─────────────────────────────────────────────────────────────────────────────
for name, d in configs:
    path = os.path.join(OUT, f'{name}.json')
    with open(path, 'w') as f:
        json.dump(d, f, indent=2)
    print(f'  {path}')

print(f'\nGenerated {len(configs)} configs in {OUT}/')
