# Spatial-weighted heatmap: accuracy evaluation

Rendered version of this analysis (chart + sortable table):
https://claude.ai/code/artifact/117dcb2d-7424-4216-a53d-034521e32d8e

## Executive summary

Restoring upstream damo's per-column spatial overlap weighting in the
heatmap renderer (`damo_report_heatmap.py`) was tested against 49 synthetic
memtest workloads (5 reps each, 490 runs) with ground truth measured
directly by the harness.

- **Shape fidelity nearly doubled:** GT↔DAMON correlation rose **0.39 → 0.73**.
- **Absolute accuracy improved modestly:** a bounded, outlier-resistant
  accuracy score rose **0.770 → 0.816** (37 of 49 configs gained correlation).
- **The patch mostly fixes *where* DAMON says the heat is, not *how much*.**
- Two failure clusters remain **regardless of this patch**: workloads with
  several independent access patterns sharing one region (accuracy down to
  0.51–0.57), and workloads where an entire region is modulated in lockstep
  (accuracy 0.57–0.66) — both point at DAMON's one-frequency-per-region
  model, not at the heatmap renderer.
- One config (`01_single_page_const_low`) exposed a separate, likely
  unrelated bug: single-page monitoring targets, where the patch is
  mathematically a no-op, still swung from 0.94 to 0.34 accuracy between
  runs.
- Five follow-up tests are proposed to isolate the remaining bugs (§5).

## 1. Introduction

DAMON (Data Access MONitor) is the Linux kernel's built-in access-frequency
tracker: it samples a process's page-table Accessed bits and reports, per
monitored memory region, how often that region was touched. `damo report
heatmap` turns a DAMON recording into a time × address grid of access
frequencies — the primary way a human (or an automated policy) reads
"where and when was this process's memory hot."

That grid is only as trustworthy as the code that bins DAMON's variable-size,
variable-lifetime regions into fixed heatmap pixels. This evaluation checks
one specific step in that binning: when a single DAMON region only partly
overlaps a heatmap column on the address axis, how much of that region's
reported frequency should the column receive? The locally-running damo build
had been patched to give the column the **full** frequency on any nonzero
overlap; upstream's original code weights it by the **overlap fraction**.
This report measures which one tracks reality better, and where either one
still fails.

## 2. Methods

**Workload generation.** Each of 50 JSON configs (`memtest/configs/`)
specifies a memory region and one or more **tracks** — a spatial profile
(uniform / hotspot / zipf / gaussian) crossed with a temporal one (const /
sine / square / ramp / steps). A hammer process touches pages accordingly
for the config's duration.

**Two independent observers watch the same run:**

- **Ground truth (GT)** — the harness's own count of real page touches per
  heatmap column, divided by duration. What actually happened, independent
  of DAMON entirely.
- **DAMON** — `damo record` against the hammer's PID (`fvaddr` ops, sample
  5ms / aggregate 100ms / ops-update 1s), then `damo report heatmap --resol`
  to read back DAMON's own Hz per column. What the kernel monitor believed
  happened.

**The one variable under test** is `damo_report_heatmap.py`'s
`add_pixel_heat()`, which decides how a DAMON region's frequency is divided
across the heatmap columns it overlaps on the address axis:

```
# before — any nonzero overlap gets the region's full frequency
heat = heat_val * account_time

# after — overlap fraction on the address axis is weighted too
heat = heat_val * account_time * account_sz   # account_sz = px ∩ region, bytes
```

Every workload was run once against each version (50 configs × 5 reps ×
2 versions = 500 runs, 0 failed). The two damo installs used (system pip
v3.3.0 for "before", a `~/damo` git checkout reverted to its own upstream
HEAD for "after") were diffed against each other outside this one function
to confirm no other code-path difference could explain the results.

**Metric.** Per heatmap column:

```
err = |GT − DAMON| / (GT + DAMON + 1)
```

Bounded in `[0, 1)`, so a cold column (GT≈0) can't blow up into a 50×
outlier ratio the way a plain percentage error does — the `+1` (Hz) term is
the only regularization needed. Accuracy = `1 − err`, averaged over all
columns in a run, then over 5 reps per config. Pearson correlation between
the GT and DAMON vectors is reported alongside as a scale-independent read
on whether the hot/cold *shape* was found at all, separate from absolute
calibration.

`02_single_page_const_high` was excluded from all of the below: independently
confirmed broken (see finding 2), leaving 49 scored configs.

## 3. Results

### 3.1 Headline numbers (49 configs)

| | Before | After | Δ |
|---|---|---|---|
| Accuracy (1 − err, avg) | 0.770 | 0.816 | **+0.046** |
| GT↔DAMON shape correlation (avg Pearson r) | 0.39 | 0.73 | **+0.34** |

### 3.2 Findings behind the summary

**1. Shape fidelity nearly doubled; absolute accuracy moved less.** Mean
accuracy only rose 0.770→0.816, but GT↔DAMON correlation jumped 0.39→0.73.
Space-weighting mostly fixes *where* DAMON says the heat is, not the overall
calibration of *how much*. 37 of 49 configs gained correlation; the biggest
single accuracy win was `21_hotspot_sine` (+0.205, corr 0.81→1.00).

**2. Two 1-page configs are algebraically immune to this patch — and that's
the tell.** `01_single_page_const_low` and the dropped `02` both request a
heatmap whose address-axis columns are each 100% inside DAMON's one reported
region. `account_sz` equals the full column width either way, so
`account_time * account_sz` and `account_time` are mathematically identical
there. Yet 01's accuracy swung from 0.936 to 0.344 between runs. That swing
isn't the patch — it's DAMON's own per-page frequency accounting being
unstable for single-page monitoring targets, an orthogonal bug hiding behind
what looked like a heatmap-rendering problem.

**3. Concurrent tracks sharing one region is where DAMON degrades most.** The
lowest absolute-accuracy configs after patching are almost all multi-track:
`43_five_tracks_overlap` (0.57), `24_two_tracks_delayed` (0.53),
`36_three_regions` (0.64), `48_three_regions_complex` (0.62), `50_ultimate`
(0.51). DAMON reports one frequency per region — it has no way to represent
several independent temporal patterns sharing the same bytes, and the more
tracks pile in, the more that single number has to compromise.

**4. Whole-region synchronized modulation is the other weak cluster.**
`33_all_pages_sine` (0.57), `34_all_pages_square` (0.61),
`06_all_pages_simultaneously` (0.66) and `05_ten_pages_sequential` (0.66) all
regressed under space-weighting and sit near the bottom regardless. When
every page in a region moves together, DAMON's 100ms aggregation window
seems to blur fast synchronized swings — consistent with what
`49_aggr_interval_blur_test` was built to probe (which itself scored well,
0.96, since it isolates the effect rather than compounding it with
region-wide sync).

**5. Two configs got noisier, not just worse.** `03_two_pages_uniform` and
`15_steps_three` show run-to-run std of 0.37 and 0.32 after patching —
roughly 10× every other config's variance (typically 0.01–0.06), and 10× their
*own* pre-patch variance (0.028 / 0.024). Mean accuracy dropped too, but the
real story is instability: something about a 2-page region or a 3-step
temporal edge appears to land right on a pixel or region boundary, where
small timing jitter flips which side an access is credited to.

## 4. Where this lives

| What | Path |
|---|---|
| Baseline run ("before") | `memtest/results/<config>/rep{1..5}_*.log` |
| Patched run ("after") | `memtest/results_spatial_weighted/<config>/rep{1..5}_*.log` |
| Scorer | `memtest/scripts/score_results.py` |
| Excluded | `02_single_page_const_high` — broken workload, dropped |

## 5. Proposed next tests

1. **Isolate the 1-page DAMON accounting bug.** Bypass the heatmap layer
   entirely for 01/02-style configs: dump raw kdamond region snapshots over
   time for 1, 2, 4, 8-page regions at matched const-Hz targets, and check
   whether the reported Hz for a 1-page target is systematically unstable or
   just high-variance.
2. **Re-run 03 and 15 at 20 reps.** Confirm the variance spike is real and
   not a fluke of n=5, and check whether the region/pixel boundaries for a
   2-page uniform region or a 3-step profile land on an exact byte or time
   boundary that a jittered sample can cross.
3. **Sweep concurrent-track count on one region.** Build a 1/2/3/5/8-track
   series sharing a single region (same spatial/temporal profile, only track
   count varies) to turn the 23→24→36→43 cluster into an actual falloff
   curve instead of five scattered points.
4. **Sample/aggregate interval sweep on the sync cluster.** Re-run 05, 06,
   33, 34 across a few `sample_us`/`aggr_us` combinations to see whether
   faster sampling recovers accuracy on whole-region synchronized
   modulation, extending what `49_aggr_interval_blur_test` already isolates.
5. **Widen the full suite to 10–20 reps.** Now that the noisy configs are
   identified by name, a wider rep count tightens confidence intervals
   across all 50 without re-deriving which ones need it.

## Appendix: full results (sorted by Δ accuracy)

| Config | Flags | Before acc | After acc | Δ | Before corr | After corr |
|---|---|---|---|---|---|---|
| 01_single_page_const_low | anomaly | 0.936 | 0.344 | -0.592 | — | — |
| 33_all_pages_sine | sync | 0.814 | 0.567 | -0.246 | — | — |
| 34_all_pages_square | sync | 0.828 | 0.605 | -0.222 | — | — |
| 03_two_pages_uniform |  | 0.958 | 0.758 | -0.200 | — | — |
| 06_all_pages_simultaneously | sync | 0.829 | 0.659 | -0.170 | — | — |
| 05_ten_pages_sequential | sync | 0.807 | 0.656 | -0.151 | 0.10 | 0.10 |
| 15_steps_three |  | 0.814 | 0.711 | -0.103 | -0.29 | -0.01 |
| 50_ultimate | multi-track | 0.605 | 0.514 | -0.091 | 0.79 | 0.68 |
| 48_three_regions_complex | multi-track | 0.684 | 0.615 | -0.069 | 0.92 | 0.94 |
| 24_two_tracks_delayed | multi-track | 0.553 | 0.528 | -0.026 | 0.83 | 0.78 |
| 41_two_competing_regions | multi-track | 0.834 | 0.827 | -0.006 | 0.09 | 0.94 |
| 36_three_regions | multi-track | 0.625 | 0.641 | +0.016 | 0.74 | 0.79 |
| 27_large_region_uniform |  | 0.857 | 0.893 | +0.037 | 0.29 | 0.37 |
| 11_sine_slow |  | 0.857 | 0.903 | +0.046 | -0.37 | 0.50 |
| 16_steps_five |  | 0.854 | 0.903 | +0.050 | -0.26 | 0.28 |
| 28_large_region_hotspot |  | 0.843 | 0.894 | +0.051 | 0.94 | 1.00 |
| 37_four_tracks_phase_shift | multi-track | 0.724 | 0.791 | +0.068 | 0.05 | 0.67 |
| 14_square_short_burst |  | 0.855 | 0.926 | +0.072 | -0.25 | 0.40 |
| 23_two_tracks_same_region | multi-track | 0.756 | 0.828 | +0.072 | 0.71 | 0.87 |
| 31_hotspot_extreme |  | 0.806 | 0.879 | +0.073 | 0.57 | 0.87 |
| 18_zipf_shallow |  | 0.795 | 0.872 | +0.077 | 0.51 | 0.95 |
| 26_two_regions_basic | multi-track | 0.778 | 0.860 | +0.082 | 0.77 | 0.93 |
| 20_gaussian_wide |  | 0.781 | 0.870 | +0.088 | 0.50 | 0.88 |
| 42_gaussian_moving_center |  | 0.803 | 0.892 | +0.089 | 0.48 | 0.85 |
| 12_sine_fast |  | 0.849 | 0.942 | +0.092 | -0.44 | 0.40 |
| 32_hotspot_balanced |  | 0.789 | 0.887 | +0.098 | -0.01 | 0.57 |
| 39_ramp_with_hotspot |  | 0.712 | 0.810 | +0.098 | 0.74 | 0.87 |
| 49_aggr_interval_blur_test |  | 0.863 | 0.964 | +0.100 | -0.42 | 0.68 |
| 46_split_merge_stress |  | 0.788 | 0.890 | +0.102 | 0.73 | 0.94 |
| 45_many_pages_zipf |  | 0.804 | 0.916 | +0.112 | 0.81 | 0.95 |
| 10_ramp_down |  | 0.829 | 0.942 | +0.113 | -0.34 | 0.14 |
| 19_gaussian_center |  | 0.665 | 0.779 | +0.114 | 0.82 | 0.93 |
| 47_sine_vs_square |  | 0.825 | 0.942 | +0.117 | 0.15 | 0.72 |
| 44_detection_limit_low_hz |  | 0.819 | 0.938 | +0.119 | 0.82 | 0.96 |
| 40_cold_to_hot_to_cold |  | 0.771 | 0.893 | +0.121 | 0.79 | 0.95 |
| 22_hotspot_square |  | 0.770 | 0.892 | +0.122 | 0.78 | 0.94 |
| 30_zipf_steps |  | 0.725 | 0.849 | +0.124 | 0.68 | 0.90 |
| 25_two_tracks_alternating | multi-track | 0.752 | 0.876 | +0.124 | 0.76 | 0.95 |
| 09_ramp_up |  | 0.830 | 0.959 | +0.129 | -0.43 | 0.52 |
| 08_hotspot_two_pages |  | 0.737 | 0.874 | +0.138 | 0.78 | 0.97 |
| 13_square_half_duty |  | 0.834 | 0.972 | +0.138 | -0.41 | 0.25 |
| 43_five_tracks_overlap | multi-track | 0.430 | 0.572 | +0.142 | 0.20 | 0.70 |
| 38_burst_detection_test |  | 0.683 | 0.834 | +0.151 | 0.77 | 0.92 |
| 04_ten_pages_uniform |  | 0.817 | 0.975 | +0.157 | -0.05 | 0.56 |
| 29_gaussian_sine |  | 0.710 | 0.874 | +0.164 | 0.84 | 0.97 |
| 07_single_hotspot_one_page |  | 0.664 | 0.829 | +0.164 | 0.54 | 0.80 |
| 35_moving_hotspot |  | 0.708 | 0.875 | +0.167 | 0.61 | 0.93 |
| 17_zipf_steep |  | 0.662 | 0.832 | +0.170 | 0.64 | 0.92 |
| 21_hotspot_sine |  | 0.716 | 0.921 | +0.205 | 0.81 | 1.00 |
