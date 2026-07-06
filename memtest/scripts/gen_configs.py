#!/usr/bin/env python3
"""Generate 50 test workload configs from trivial to complex."""
import json, os

OUT = os.path.join(os.path.dirname(__file__), '..', 'configs')
os.makedirs(OUT, exist_ok=True)

configs = []

def cfg(name, duration, regions, tracks, t_rows=None, s_cols=None):
    n_pages = regions[0]['pages']
    d = {
        'duration_sec': duration,
        'heatmap_time_rows':  t_rows  or duration,
        'heatmap_space_cols': s_cols  or n_pages,
        'regions': regions,
        'tracks':  tracks,
    }
    configs.append((name, d))

# ── TRIVIAL (1-10) ────────────────────────────────────────────────────────────

cfg('01_single_page_const_low',
    duration=10, regions=[{'pages':1}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'const','hz':10},
        'start_sec':0,'end_sec':10}])

cfg('02_single_page_const_high',
    duration=10, regions=[{'pages':1}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'const','hz':200},
        'start_sec':0,'end_sec':10}])

cfg('03_two_pages_uniform',
    duration=10, regions=[{'pages':2}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'const','hz':100},
        'start_sec':0,'end_sec':10}])

cfg('04_ten_pages_uniform',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'const','hz':100},
        'start_sec':0,'end_sec':15}])

cfg('05_ten_pages_sequential',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0, 'spatial':{'type':'sequential'},
        'temporal':{'type':'const','hz':100},
        'start_sec':0,'end_sec':15}])

cfg('06_all_pages_simultaneously',
    duration=10, regions=[{'pages':10}], tracks=[{
        'region':0, 'spatial':{'type':'all'},
        'temporal':{'type':'const','hz':50},
        'start_sec':0,'end_sec':10}])

cfg('07_single_hotspot_one_page',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0],'hot_ratio':0.95},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('08_hotspot_two_pages',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('09_ramp_up',
    duration=15, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'ramp','start_hz':0,'end_hz':200},
        'start_sec':0,'end_sec':15}])

cfg('10_ramp_down',
    duration=15, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'ramp','start_hz':200,'end_hz':0},
        'start_sec':0,'end_sec':15}])

# ── SIMPLE (11-20) ────────────────────────────────────────────────────────────

cfg('11_sine_slow',
    duration=20, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':4.0},
        'start_sec':0,'end_sec':20}])

cfg('12_sine_fast',
    duration=20, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':0.5},
        'start_sec':0,'end_sec':20}])

cfg('13_square_half_duty',
    duration=20, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'square','on_hz':200,'duty':0.5,'period_sec':2.0},
        'start_sec':0,'end_sec':20}])

cfg('14_square_short_burst',
    duration=20, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'square','on_hz':200,'duty':0.05,'period_sec':1.0},
        'start_sec':0,'end_sec':20}])

cfg('15_steps_three',
    duration=15, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'steps','steps':[
            {'hz':20,'duration_sec':5},
            {'hz':120,'duration_sec':5},
            {'hz':60,'duration_sec':5}]},
        'start_sec':0,'end_sec':15}])

cfg('16_steps_five',
    duration=25, regions=[{'pages':5}], tracks=[{
        'region':0, 'spatial':{'type':'uniform'},
        'temporal':{'type':'steps','steps':[
            {'hz':10,'duration_sec':5},
            {'hz':50,'duration_sec':5},
            {'hz':100,'duration_sec':5},
            {'hz':150,'duration_sec':5},
            {'hz':200,'duration_sec':5}]},
        'start_sec':0,'end_sec':25}])

cfg('17_zipf_steep',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'zipf','s':2.0},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('18_zipf_shallow',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'zipf','s':0.5},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('19_gaussian_center',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'gaussian','center':4.5,'sigma':1.0},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('20_gaussian_wide',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'gaussian','center':4.5,'sigma':3.0},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

# ── MEDIUM (21-35) ────────────────────────────────────────────────────────────

cfg('21_hotspot_sine',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
        'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':2.0},
        'start_sec':0,'end_sec':20}])

cfg('22_hotspot_square',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
        'temporal':{'type':'square','on_hz':200,'duty':0.3,'period_sec':2.0},
        'start_sec':0,'end_sec':20}])

cfg('23_two_tracks_same_region',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1,2],'hot_ratio':0.8},
         'temporal':{'type':'const','hz':100},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[7,8,9],'hot_ratio':0.8},
         'temporal':{'type':'const','hz':100},
         'start_sec':0,'end_sec':20}])

cfg('24_two_tracks_delayed',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'uniform'},
         'temporal':{'type':'const','hz':100},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'const','hz':150},
         'start_sec':10,'end_sec':20}])

cfg('25_two_tracks_alternating',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1,2],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':150,'duty':0.5,'period_sec':4.0},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[7,8,9],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':150,'duty':0.5,'period_sec':4.0,'phase_rad':3.14159},
         'start_sec':0,'end_sec':20}])

cfg('26_two_regions_basic',
    duration=15,
    regions=[{'pages':10},{'pages':10}],
    tracks=[
        {'region':0,'spatial':{'type':'uniform'},
         'temporal':{'type':'const','hz':100},'start_sec':0,'end_sec':15},
        {'region':1,'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'const','hz':150},'start_sec':0,'end_sec':15}],
    s_cols=10)

cfg('27_large_region_uniform',
    duration=15, regions=[{'pages':50}], tracks=[{
        'region':0,'spatial':{'type':'uniform'},
        'temporal':{'type':'const','hz':100},
        'start_sec':0,'end_sec':15}], s_cols=50)

cfg('28_large_region_hotspot',
    duration=15, regions=[{'pages':50}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1,2,3,4],'hot_ratio':0.9},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}], s_cols=50)

cfg('29_gaussian_sine',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'gaussian','center':2.0,'sigma':1.5},
        'temporal':{'type':'sine','base_hz':80,'amplitude':60,'period_sec':3.0},
        'start_sec':0,'end_sec':20}])

cfg('30_zipf_steps',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'zipf','s':1.5},
        'temporal':{'type':'steps','steps':[
            {'hz':30,'duration_sec':5},
            {'hz':100,'duration_sec':5},
            {'hz':180,'duration_sec':5},
            {'hz':50,'duration_sec':5}]},
        'start_sec':0,'end_sec':20}])

cfg('31_hotspot_extreme',
    duration=15, regions=[{'pages':20}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0],'hot_ratio':0.99},
        'temporal':{'type':'const','hz':200},
        'start_sec':0,'end_sec':15}], s_cols=20)

cfg('32_hotspot_balanced',
    duration=15, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1,2,3,4],'hot_ratio':0.5},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':15}])

cfg('33_all_pages_sine',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,'spatial':{'type':'all'},
        'temporal':{'type':'sine','base_hz':60,'amplitude':50,'period_sec':3.0},
        'start_sec':0,'end_sec':20}])

cfg('34_all_pages_square',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,'spatial':{'type':'all'},
        'temporal':{'type':'square','on_hz':150,'duty':0.4,'period_sec':2.0},
        'start_sec':0,'end_sec':20}])

cfg('35_moving_hotspot',
    duration=30, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'const','hz':150},'start_sec':0,'end_sec':10},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[4,5],'hot_ratio':0.9},
         'temporal':{'type':'const','hz':150},'start_sec':10,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[8,9],'hot_ratio':0.9},
         'temporal':{'type':'const','hz':150},'start_sec':20,'end_sec':30}],
    t_rows=30)

# ── COMPLEX (36-50) ───────────────────────────────────────────────────────────

cfg('36_three_regions',
    duration=20,
    regions=[{'pages':5},{'pages':10},{'pages':20}],
    tracks=[
        {'region':0,'spatial':{'type':'uniform'},
         'temporal':{'type':'const','hz':200},'start_sec':0,'end_sec':20},
        {'region':1,'spatial':{'type':'zipf','s':1.5},
         'temporal':{'type':'sine','base_hz':80,'amplitude':60,'period_sec':2.0},
         'start_sec':0,'end_sec':20},
        {'region':2,'spatial':{'type':'hotspot','hot_pages':[0,1,2],'hot_ratio':0.85},
         'temporal':{'type':'square','on_hz':150,'duty':0.4,'period_sec':3.0},
         'start_sec':0,'end_sec':20}],
    t_rows=20, s_cols=20)

cfg('37_four_tracks_phase_shift',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':80,'amplitude':70,'period_sec':4.0,'phase_rad':0.0},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[2,3],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':80,'amplitude':70,'period_sec':4.0,'phase_rad':1.57},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[5,6],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':80,'amplitude':70,'period_sec':4.0,'phase_rad':3.14},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[8,9],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':80,'amplitude':70,'period_sec':4.0,'phase_rad':4.71},
         'start_sec':0,'end_sec':20}])

cfg('38_burst_detection_test',
    duration=30, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':200,'duty':0.5,'period_sec':1.0},
         'start_sec':0,'end_sec':30},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[4,5],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':200,'duty':0.1,'period_sec':1.0},
         'start_sec':0,'end_sec':30},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[8,9],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':200,'duty':0.02,'period_sec':1.0},
         'start_sec':0,'end_sec':30}],
    t_rows=30)

cfg('39_ramp_with_hotspot',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'ramp','start_hz':0,'end_hz':200},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[8,9],'hot_ratio':0.9},
         'temporal':{'type':'ramp','start_hz':200,'end_hz':0},
         'start_sec':0,'end_sec':20}])

cfg('40_cold_to_hot_to_cold',
    duration=30, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1,2,3,4],'hot_ratio':0.9},
        'temporal':{'type':'steps','steps':[
            {'hz':5,'duration_sec':5},
            {'hz':50,'duration_sec':5},
            {'hz':150,'duration_sec':5},
            {'hz':200,'duration_sec':5},
            {'hz':50,'duration_sec':5},
            {'hz':5,'duration_sec':5}]},
        'start_sec':0,'end_sec':30}],
    t_rows=30)

cfg('41_two_competing_regions',
    duration=20,
    regions=[{'pages':10},{'pages':10}],
    tracks=[
        {'region':0,'spatial':{'type':'all'},
         'temporal':{'type':'square','on_hz':150,'duty':0.5,'period_sec':4.0},
         'start_sec':0,'end_sec':20},
        {'region':1,'spatial':{'type':'all'},
         'temporal':{'type':'square','on_hz':150,'duty':0.5,'period_sec':4.0,'phase_rad':3.14},
         'start_sec':0,'end_sec':20}],
    t_rows=20, s_cols=10)

cfg('42_gaussian_moving_center',
    duration=30, regions=[{'pages':20}], tracks=[
        {'region':0,
         'spatial':{'type':'gaussian','center':2.0,'sigma':2.0},
         'temporal':{'type':'const','hz':150},'start_sec':0,'end_sec':10},
        {'region':0,
         'spatial':{'type':'gaussian','center':10.0,'sigma':2.0},
         'temporal':{'type':'const','hz':150},'start_sec':10,'end_sec':20},
        {'region':0,
         'spatial':{'type':'gaussian','center':17.0,'sigma':2.0},
         'temporal':{'type':'const','hz':150},'start_sec':20,'end_sec':30}],
    t_rows=30, s_cols=20)

cfg('43_five_tracks_overlap',
    duration=25, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0],'hot_ratio':0.95},
         'temporal':{'type':'const','hz':100},'start_sec':0,'end_sec':25},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[2],'hot_ratio':0.95},
         'temporal':{'type':'const','hz':100},'start_sec':5,'end_sec':25},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[4],'hot_ratio':0.95},
         'temporal':{'type':'const','hz':100},'start_sec':10,'end_sec':25},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[6],'hot_ratio':0.95},
         'temporal':{'type':'const','hz':100},'start_sec':15,'end_sec':25},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[8],'hot_ratio':0.95},
         'temporal':{'type':'const','hz':100},'start_sec':20,'end_sec':25}],
    t_rows=25)

cfg('44_detection_limit_low_hz',
    duration=20, regions=[{'pages':10}], tracks=[{
        'region':0,
        'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
        'temporal':{'type':'steps','steps':[
            {'hz':1,'duration_sec':4},
            {'hz':5,'duration_sec':4},
            {'hz':10,'duration_sec':4},
            {'hz':20,'duration_sec':4},
            {'hz':50,'duration_sec':4}]},
        'start_sec':0,'end_sec':20}])

cfg('45_many_pages_zipf',
    duration=20, regions=[{'pages':30}], tracks=[{
        'region':0,
        'spatial':{'type':'zipf','s':1.2},
        'temporal':{'type':'const','hz':150},
        'start_sec':0,'end_sec':20}], s_cols=30)

cfg('46_split_merge_stress',
    duration=30, regions=[{'pages':16}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1,2,3],'hot_ratio':0.7},
         'temporal':{'type':'const','hz':200},'start_sec':0,'end_sec':15},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[12,13,14,15],'hot_ratio':0.7},
         'temporal':{'type':'const','hz':200},'start_sec':15,'end_sec':30},
        {'region':0,
         'spatial':{'type':'uniform'},
         'temporal':{'type':'const','hz':20},'start_sec':0,'end_sec':30}],
    t_rows=30, s_cols=16)

cfg('47_sine_vs_square',
    duration=20, regions=[{'pages':10}], tracks=[
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[0,1,2,3,4],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':2.0},
         'start_sec':0,'end_sec':20},
        {'region':0,
         'spatial':{'type':'hotspot','hot_pages':[5,6,7,8,9],'hot_ratio':0.9},
         'temporal':{'type':'square','on_hz':180,'duty':0.5,'period_sec':2.0},
         'start_sec':0,'end_sec':20}])

cfg('48_three_regions_complex',
    duration=25,
    regions=[{'pages':5},{'pages':10},{'pages':15}],
    tracks=[
        {'region':0,'spatial':{'type':'all'},
         'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':5.0},
         'start_sec':0,'end_sec':25},
        {'region':1,'spatial':{'type':'hotspot','hot_pages':[0,1,2],'hot_ratio':0.85},
         'temporal':{'type':'ramp','start_hz':0,'end_hz':200},
         'start_sec':0,'end_sec':25},
        {'region':1,'spatial':{'type':'hotspot','hot_pages':[7,8,9],'hot_ratio':0.85},
         'temporal':{'type':'ramp','start_hz':200,'end_hz':0},
         'start_sec':0,'end_sec':25},
        {'region':2,'spatial':{'type':'gaussian','center':7.0,'sigma':3.0},
         'temporal':{'type':'square','on_hz':150,'duty':0.3,'period_sec':2.0},
         'start_sec':5,'end_sec':20}],
    t_rows=25, s_cols=15)

cfg('49_aggr_interval_blur_test',
    duration=20, regions=[{'pages':5}], tracks=[
        {'region':0,'spatial':{'type':'uniform'},
         'temporal':{'type':'square','on_hz':200,'duty':0.5,'period_sec':0.2},
         'start_sec':0,'end_sec':20},   # period < 2×aggr_interval → blurred
        {'region':0,'spatial':{'type':'uniform'},
         'temporal':{'type':'square','on_hz':200,'duty':0.5,'period_sec':2.0},
         'start_sec':0,'end_sec':0}])   # disabled, just doc

cfg('50_ultimate',
    duration=40,
    regions=[{'pages':8},{'pages':16},{'pages':4}],
    tracks=[
        {'region':0,'spatial':{'type':'hotspot','hot_pages':[0,1],'hot_ratio':0.9},
         'temporal':{'type':'sine','base_hz':100,'amplitude':80,'period_sec':3.0},
         'start_sec':0,'end_sec':40},
        {'region':0,'spatial':{'type':'zipf','s':1.5},
         'temporal':{'type':'square','on_hz':150,'duty':0.3,'period_sec':2.0},
         'start_sec':10,'end_sec':30},
        {'region':1,'spatial':{'type':'gaussian','center':8.0,'sigma':3.0},
         'temporal':{'type':'ramp','start_hz':0,'end_hz':200},
         'start_sec':0,'end_sec':20},
        {'region':1,'spatial':{'type':'hotspot','hot_pages':[0,1,2,3],'hot_ratio':0.85},
         'temporal':{'type':'steps','steps':[
             {'hz':20,'duration_sec':10},{'hz':150,'duration_sec':10},
             {'hz':80,'duration_sec':10},{'hz':200,'duration_sec':10}]},
         'start_sec':0,'end_sec':40},
        {'region':2,'spatial':{'type':'all'},
         'temporal':{'type':'square','on_hz':200,'duty':0.5,'period_sec':4.0},
         'start_sec':5,'end_sec':35}],
    t_rows=40, s_cols=16)

# ── write files ───────────────────────────────────────────────────────────────

for name, d in configs:
    path = os.path.join(OUT, f'{name}.json')
    with open(path, 'w') as f:
        json.dump(d, f, indent=2)
    print(f'  {path}')

print(f'\nGenerated {len(configs)} configs in {OUT}/')
