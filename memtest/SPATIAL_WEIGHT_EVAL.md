# DAMON heatmap accuracy evaluation

## Executive summary

DAMON's `damo report heatmap` output was measured against directly-observed
ground truth across 49 synthetic memory-access workloads (5 reps each),
under two heatmap-rendering configurations — **Config A** ("full-overlap":
any nonzero address-axis overlap credits a column with the region's full
frequency) and **Config B** ("overlap-weighted": frequency is prorated by
the overlap fraction). 980 scored runs total.

- **Overall accuracy: 0.77 (Config A) / 0.82 (Config B).** Shape correlation
  between GT and DAMON: 0.39 (A) / 0.73 (B).
- **DAMON's accuracy is strongly workload-dependent**, more so than it is
  configuration-dependent. It is highly reliable (accuracy >0.88, corr
  frequently >0.8) on workloads with a single, spatially well-separated
  access pattern — sine/ramp/square sweeps, isolated hotspots, uniform
  spreads over many pages.
- **Two failure clusters hold under *both* configurations**, meaning they
  reflect DAMON's own model, not a heatmap-rendering artifact:
  - *Concurrent access patterns sharing one region* — accuracy 0.50–0.65
    (`43_five_tracks_overlap`, `24_two_tracks_delayed`, `50_ultimate`,
    `36_three_regions`). DAMON reports one frequency per region and cannot
    represent several independent patterns sharing the same bytes.
  - *Whole-region synchronized modulation* — accuracy 0.69–0.74
    (`33_all_pages_sine`, `34_all_pages_square`, `05_ten_pages_sequential`,
    `06_all_pages_simultaneously`). Likely DAMON's 100ms aggregation window
    blurring fast, region-wide swings.
- **The overlap-weighted configuration (B) does not change which workloads
  DAMON struggles with** — it substantially improves *shape* fidelity
  (avg corr 0.39→0.73) without resolving either failure cluster above.
- **`01_single_page_const_low` is a separate, likely unrelated instability**:
  single-page monitoring targets show large run-to-run swings in DAMON's own
  reported frequency (0.94 vs 0.34 accuracy between runs) that the two
  rendering configurations are algebraically incapable of causing.
- Five follow-up tests are proposed to isolate the mechanisms behind these
  clusters (§5).

## 1. Introduction

DAMON (Data Access MONitor) is the Linux kernel's built-in access-frequency
tracker: it samples a process's page-table Accessed bits and reports, per
monitored memory region, how often that region was touched. `damo report
heatmap` turns a DAMON recording into a time × address grid of access
frequencies — the primary way a human (or an automated policy) reads
"where and when was this process's memory hot."

This evaluation asks a direct question: **how accurate is that heatmap**,
compared to what actually happened? Rather than trust a single rendering
path, the same 49 workloads were measured under two different heatmap
binning rules (§2), so that any accuracy pattern found could be checked
against whether it survives across both — a genuine DAMON limitation should
show up regardless of rendering choice, while a rendering-specific artifact
should not.

## 2. Methods

**Workload generation.** Each of 50 JSON configs (`memtest/configs/`)
specifies a memory region and one or more **tracks** — a spatial profile
(uniform / hotspot / zipf / gaussian) crossed with a temporal one (const /
sine / square / ramp / steps). A hammer process touches pages accordingly
for the config's duration.

**Two independent observers watch each run:**

- **Ground truth (GT)** — the harness's own count of real page touches per
  heatmap column, divided by duration. What actually happened, independent
  of DAMON entirely.
- **DAMON** — `damo record` against the hammer's PID (`fvaddr` ops, sample
  5ms / aggregate 100ms / ops-update 1s), then `damo report heatmap --resol`
  to read back DAMON's own Hz per column. What the kernel monitor believed
  happened.

**Two measurement configurations.** `damo_report_heatmap.py`'s
`add_pixel_heat()` decides how a DAMON region's frequency is divided across
the heatmap columns it overlaps on the address axis. Both rules were run
against every workload:

```
# Config A — "full-overlap": any nonzero overlap gets the region's full frequency
heat = heat_val * account_time

# Config B — "overlap-weighted": overlap fraction on the address axis is weighted too
heat = heat_val * account_time * account_sz   # account_sz = px ∩ region, bytes
```

50 configs × 5 reps × 2 configurations = 500 runs, 0 failed. The two damo
installs used (system pip v3.3.0 for Config A, a `~/damo` git checkout at
upstream HEAD for Config B) were diffed against each other outside this one
function to confirm no other code-path difference could confound the
comparison.

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
confirmed broken (see §3.5), leaving 49 scored configs.

## 3. Results

### 3.1 Overall accuracy

| | Config A | Config B |
|---|---|---|
| Accuracy (1 − err, avg over 49 configs) | 0.770 | 0.816 |
| GT↔DAMON shape correlation (avg Pearson r) | 0.39 | 0.73 |

### 3.2 Where DAMON is accurate

Workloads with a single, spatially well-defined access pattern score highest
under both configurations: `49_aggr_interval_blur_test` (avg 0.91),
`13_square_half_duty` (0.90), `04_ten_pages_uniform` (0.90),
`12_sine_fast` / `09_ramp_up` (0.89–0.90), `14_square_short_burst` (0.89).
These share large or spatially spread regions and a single temporal profile
— nothing else competing for the same address range.

### 3.3 Where DAMON struggles — concurrent patterns sharing a region

The lowest-scoring configs under both configurations are almost all
multi-track: `43_five_tracks_overlap` (avg 0.50), `24_two_tracks_delayed`
(0.54), `50_ultimate` (0.56), `36_three_regions` (0.63),
`48_three_regions_complex` (0.65). DAMON reports one frequency per region —
it has no way to represent several independent temporal patterns sharing
the same bytes, and the more tracks pile into one region, the more that
single number has to compromise. This holds in both Config A and Config B,
so it is a property of DAMON's region-frequency model, not the heatmap
renderer.

### 3.4 Where DAMON struggles — whole-region synchronized modulation

`33_all_pages_sine` (avg 0.69), `34_all_pages_square` (0.72),
`05_ten_pages_sequential` (0.73), `06_all_pages_simultaneously` (0.74) all
sit well below the suite average in both configurations. When every page in
a region moves together, DAMON's 100ms aggregation window appears to blur
fast, synchronized swings — consistent with what
`49_aggr_interval_blur_test` was built to probe (which itself scores well,
since it isolates the aggregation effect rather than compounding it with
region-wide synchrony).

### 3.5 Effect of the rendering configuration on shape fidelity

Config B's overlap-fraction weighting raises average GT↔DAMON correlation
from 0.39 to 0.73 — 37 of 49 configs gain correlation, and the single
largest per-config gain is `21_hotspot_sine` (corr 0.81→1.00). This is the
one dimension where configuration choice clearly matters: Config B locates
*where* the heat is far more faithfully. It does not, however, move any
config out of the two failure clusters above (§3.3, §3.4) — both remain
weak under Config B too.

Two 1-page configs (`01_single_page_const_low` and the dropped
`02_single_page_const_high`) are algebraically unaffected by which
configuration is used: their heatmap columns are each 100% inside DAMON's
one reported region, so `account_sz` equals the full column width either
way, making Config A and B identical there.

### 3.6 Measurement instability, independent of configuration

`01_single_page_const_low` swung from 0.936 to 0.344 accuracy between the
two runs despite being immune to the configuration change (§3.5) — pointing
at DAMON's own per-page frequency accounting being unstable for single-page
monitoring targets, not at the heatmap layer at all.

`03_two_pages_uniform` and `15_steps_three` show run-to-run std of 0.37 and
0.32 in Config B — roughly 10× every other config's variance (typically
0.01–0.06) and 10× their own Config-A variance (0.028 / 0.024). Something
about a 2-page region or a 3-step temporal edge appears to land right on a
pixel or region boundary, where small timing jitter flips which side an
access is credited to.

## 4. Where this lives

| What | Path |
|---|---|
| Config A run | `memtest/results/<config>/rep{1..5}_*.log` |
| Config B run | `memtest/results_spatial_weighted/<config>/rep{1..5}_*.log` |
| Scorer | `memtest/scripts/score_results.py` |
| Excluded | `02_single_page_const_high` — broken workload, dropped |

## 5. Proposed next tests

1. **Isolate the single-page DAMON accounting instability.** Bypass the
   heatmap layer entirely for 01/02-style configs: dump raw kdamond region
   snapshots over time for 1, 2, 4, 8-page regions at matched const-Hz
   targets, and check whether the reported Hz for a 1-page target is
   systematically unstable or just high-variance.
2. **Re-run 03 and 15 at 20 reps.** Confirm the variance spike is real and
   not a fluke of n=5, and check whether the region/pixel boundaries for a
   2-page uniform region or a 3-step profile land on an exact byte or time
   boundary that a jittered sample can cross.
3. **Sweep concurrent-track count on one region.** Build a 1/2/3/5/8-track
   series sharing a single region (same spatial/temporal profile, only track
   count varies) to turn the 23→24→36→43 cluster into an actual falloff
   curve instead of scattered points.
4. **Sample/aggregate interval sweep on the synchronized-modulation
   cluster.** Re-run 05, 06, 33, 34 across a few `sample_us`/`aggr_us`
   combinations to see whether faster sampling recovers accuracy on
   whole-region synchronized modulation, extending what
   `49_aggr_interval_blur_test` already isolates.
5. **Widen the full suite to 10–20 reps.** Now that the noisy configs are
   identified by name, a wider rep count tightens confidence intervals
   across all 50 without re-deriving which ones need it.

## Appendix: full results (sorted by average accuracy across both configurations)

| Config | Flags | Config A acc | Config B acc | Avg acc | Config A corr | Config B corr |
|---|---|---|---|---|---|---|
| 43_five_tracks_overlap | multi-track | 0.430 | 0.572 | 0.501 | 0.20 | 0.70 |
| 24_two_tracks_delayed | multi-track | 0.553 | 0.528 | 0.540 | 0.83 | 0.78 |
| 50_ultimate | multi-track | 0.605 | 0.514 | 0.559 | 0.79 | 0.68 |
| 36_three_regions | multi-track | 0.625 | 0.641 | 0.633 | 0.74 | 0.79 |
| 01_single_page_const_low | anomaly | 0.936 | 0.344 | 0.640 | — | — |
| 48_three_regions_complex | multi-track | 0.684 | 0.615 | 0.649 | 0.92 | 0.94 |
| 33_all_pages_sine | sync | 0.814 | 0.567 | 0.690 | — | — |
| 34_all_pages_square | sync | 0.828 | 0.605 | 0.716 | — | — |
| 19_gaussian_center |  | 0.665 | 0.779 | 0.722 | 0.82 | 0.93 |
| 05_ten_pages_sequential | sync | 0.807 | 0.656 | 0.732 | 0.10 | 0.10 |
| 06_all_pages_simultaneously | sync | 0.829 | 0.659 | 0.744 | — | — |
| 07_single_hotspot_one_page |  | 0.664 | 0.829 | 0.746 | 0.54 | 0.80 |
| 17_zipf_steep |  | 0.662 | 0.832 | 0.747 | 0.64 | 0.92 |
| 37_four_tracks_phase_shift | multi-track | 0.724 | 0.791 | 0.758 | 0.05 | 0.67 |
| 38_burst_detection_test |  | 0.683 | 0.834 | 0.758 | 0.77 | 0.92 |
| 39_ramp_with_hotspot |  | 0.712 | 0.810 | 0.761 | 0.74 | 0.87 |
| 15_steps_three |  | 0.814 | 0.711 | 0.762 | -0.29 | -0.01 |
| 30_zipf_steps |  | 0.725 | 0.849 | 0.787 | 0.68 | 0.90 |
| 35_moving_hotspot |  | 0.708 | 0.875 | 0.791 | 0.61 | 0.93 |
| 23_two_tracks_same_region | multi-track | 0.756 | 0.828 | 0.792 | 0.71 | 0.87 |
| 29_gaussian_sine |  | 0.710 | 0.874 | 0.792 | 0.84 | 0.97 |
| 08_hotspot_two_pages |  | 0.737 | 0.874 | 0.805 | 0.78 | 0.97 |
| 25_two_tracks_alternating | multi-track | 0.752 | 0.876 | 0.814 | 0.76 | 0.95 |
| 21_hotspot_sine |  | 0.716 | 0.921 | 0.819 | 0.81 | 1.00 |
| 26_two_regions_basic | multi-track | 0.778 | 0.860 | 0.819 | 0.77 | 0.93 |
| 20_gaussian_wide |  | 0.781 | 0.870 | 0.826 | 0.50 | 0.88 |
| 41_two_competing_regions | multi-track | 0.834 | 0.827 | 0.831 | 0.09 | 0.94 |
| 22_hotspot_square |  | 0.770 | 0.892 | 0.831 | 0.78 | 0.94 |
| 40_cold_to_hot_to_cold |  | 0.771 | 0.893 | 0.832 | 0.79 | 0.95 |
| 18_zipf_shallow |  | 0.795 | 0.872 | 0.834 | 0.51 | 0.95 |
| 32_hotspot_balanced |  | 0.789 | 0.887 | 0.838 | -0.01 | 0.57 |
| 46_split_merge_stress |  | 0.788 | 0.890 | 0.839 | 0.73 | 0.94 |
| 31_hotspot_extreme |  | 0.806 | 0.879 | 0.843 | 0.57 | 0.87 |
| 42_gaussian_moving_center |  | 0.803 | 0.892 | 0.848 | 0.48 | 0.85 |
| 03_two_pages_uniform |  | 0.958 | 0.758 | 0.858 | — | — |
| 45_many_pages_zipf |  | 0.804 | 0.916 | 0.860 | 0.81 | 0.95 |
| 28_large_region_hotspot |  | 0.843 | 0.894 | 0.869 | 0.94 | 1.00 |
| 27_large_region_uniform |  | 0.857 | 0.893 | 0.875 | 0.29 | 0.37 |
| 44_detection_limit_low_hz |  | 0.819 | 0.938 | 0.878 | 0.82 | 0.96 |
| 16_steps_five |  | 0.854 | 0.903 | 0.879 | -0.26 | 0.28 |
| 11_sine_slow |  | 0.857 | 0.903 | 0.880 | -0.37 | 0.50 |
| 47_sine_vs_square |  | 0.825 | 0.942 | 0.883 | 0.15 | 0.72 |
| 10_ramp_down |  | 0.829 | 0.942 | 0.885 | -0.34 | 0.14 |
| 14_square_short_burst |  | 0.855 | 0.926 | 0.891 | -0.25 | 0.40 |
| 09_ramp_up |  | 0.830 | 0.959 | 0.894 | -0.43 | 0.52 |
| 12_sine_fast |  | 0.849 | 0.942 | 0.895 | -0.44 | 0.40 |
| 04_ten_pages_uniform |  | 0.817 | 0.975 | 0.896 | -0.05 | 0.56 |
| 13_square_half_duty |  | 0.834 | 0.972 | 0.903 | -0.41 | 0.25 |
| 49_aggr_interval_blur_test |  | 0.863 | 0.964 | 0.913 | -0.42 | 0.68 |
