# Pacing drift in `andrey_hammer.c` — investigation, root cause, fix (FIXED)

## Where (code)

`andrey_hammer/src/andrey_hammer.c`, the touch loop inside the per-frame
loop. Original (buggy) version:

```c
long interval_ns = (long)((frame_dt_ms * 1e6) / (double)si);  // si = touches this frame
for (i = 0; i < si; i++) {
    *touch;
    fprintf(gt, ...);
    if (interval_ns > 50000) sleep_ns(interval_ns);  // fixed relative interval, every touch
}
```

and the end-of-frame padding:

```c
long remaining_ns = (long)(frame_dt_ms * 1e6) - elapsed_ns;
sleep_ns(remaining_ns);   // pad out to nominal frame_dt_ms
```

## Symptom

`andrey_hammer` frames ran well over their nominal `frame_dt_ms`
(configured, from `meta.json`, typically ~100ms) — measured mean 139.03ms
(+38%) in one run, with real frame-to-frame variance (stdev 11.15ms,
range 112–184ms). `remaining_ns` in the end-of-frame padding regularly
went negative once a frame was already running long, so `sleep_ns` there
did nothing — no debt was ever carried or repaid between frames.

## Root cause — verified by direct profiling, not inferred

Added timers around each per-frame sub-phase (math, memory write,
`fprintf`, `sleep_ns`) in a throwaway instrumented build, ran the full
254-frame sequence on real `code3.json`+`meta3.json`:

| Component | Total across run | Share of total time |
|---|---|---|
| Math (10 channels + Super-Gaussian profile) | 13.69 ms | **0.04%** |
| Memory writes | 19.69 ms | 0.06% |
| `fprintf` (gt.log lines) | 114.98 ms | 0.38% |
| **`sleep_ns()` calls** | **30352.33 ms** | **99.43%** |

**Not the math** — 0.04% of total time, negligible even at 254 frames ×
10 channels × 170 bins × 3 modes. The overshoot (5007.71ms total, +19.6%)
was almost entirely (4835.23ms, 96.6%) accumulated *per-call* oversleep
inside `clock_nanosleep()` itself:

```
Expected total sleep (== nominal total):  25517.09 ms
Actual total sleep:                       30352.33 ms
Average oversleep per call:               ~86.75 us  ×  55737 calls this run
```

Each individual `clock_nanosleep()` call under WSL2 sleeps ~87
microseconds longer than requested — virtualized timer/scheduler
wake-up overhead. More touches in a frame (`si`) means more calls means
more accumulated oversleep — this is the actual mechanism behind the
touch-count/frame-duration correlation (Pearson r = 0.705) found earlier
by just eyeballing the numbers, not a separate effect.

This also killed the originally-proposed fix (compensate debt at the end
of each frame): the overshoot accumulates *inside* the touch loop's many
small sleeps, not in `remaining_ns` — which is usually already ≤0 by the
time it's reached, i.e. there's nothing left there to shrink.

## Fix — absolute-target pacing

Instead of sleeping a fixed `interval_ns` after every touch, touch *i* is
scheduled against an absolute target time (`frame_start + i*interval_ns`)
and only sleeps the actual remaining gap to that target — or skips
sleeping entirely if already at or past it:

```c
uint64_t next_target = frame_start;
for (i = 0; i < si; i++) {
    next_target += interval_ns;
    *touch;
    fprintf(gt, ...);
    uint64_t now = ts_ns();
    if (now < next_target) {
        long gap_ns = (long)(next_target - now);
        if (gap_ns > 50000) sleep_ns(gap_ns);
    }
    // else: already at/past schedule -- skip sleeping, don't compound debt
}
```

Self-correcting: an ~87us oversleep on one touch means the *next* touch's
target-check finds itself already caught up, so it just skips its own
sleep instead of stacking another full interval on top. Busy frames
naturally issue fewer sleep calls exactly when they'd otherwise
accumulate the most error — no batch-size tuning needed.

## Verified

Same real `code3.json`+`meta3.json`, 254 steps, before vs after:

| | Before | After |
|---|---|---|
| Mean frame duration | 139.03 ms (+38%) | **100.56 ms (+0.1%)** |
| stdev | 11.15 ms | **0.06 ms** |
| Range | 112–184 ms | 100.48–100.86 ms |
| Touch-count/duration correlation (r) | 0.705 | **0.017** |

Drift is essentially eliminated — both the mean overshoot and the
content-coupling are gone.

## What this did and didn't change downstream

- **`gt_to_io.py`-vs-DAMON comparison (same run, both real timestamps):**
  was never meaningfully hurt by this bug in the first place (checked
  directly — see `ANDREY_PIPELINE.md`'s "Known issues"), so no material
  change expected here from the fix.
- **Comparisons against `sim_raw3.txt`** (which has no real timestamps of
  its own, assumes a uniform frame cadence): time-profile r stayed
  ~0.29–0.31 before and after the fix — essentially unchanged. Turned out
  this residual was never mainly caused by the pacing bug: the "~0.69
  ceiling" it was originally measured against was a single lucky sample,
  not a real baseline. Re-checked across 5 seeds of Python-vs-`sim_raw3.txt`:
  range 0.20–0.44, mean ≈0.36 — `andrey_hammer`'s 0.29–0.31 was already
  normal for this passport's inherent randomness, independent of the
  pacing bug. See `ANDREY_PIPELINE.md` for the reproduction command.
- The fix is still correct and worth having on its own terms — frame
  timing is now genuinely trustworthy, not just "close enough that it
  happened not to corrupt this one metric."

## Why ~0.3 time-profile r against `sim_raw3.txt` is expected, not a bug

Not just "checked 5 seeds and it matched" — there's a direct mathematical
reason this passport can't give much more than that, independent of
pacing, DAMON, or any implementation issue.

`M_raw` (and everything downstream of it) is built as:

```
X_raw(t) = trend(t) + harmonic(t) + AR(1)-noise(t)
```

`trend` and `harmonic` are **deterministic** — same formula, same result,
in *any* run of this passport, C or Python, any seed. `AR(1)-noise` is
**genuinely random** and independent between any two separate runs.

For two independent realizations `X_A = det(t) + noise_A(t)` and
`X_B = det(t) + noise_B(t)` of the same process (`noise_A` and `noise_B`
uncorrelated), the correlation between them is exactly:

```
r = Var(det) / (Var(det) + Var(noise))
```

(covariance of the noise terms is zero by independence, so only the
shared deterministic part contributes to `Cov(X_A, X_B)`).

Plugging in `code3.json`'s actual `M_raw` parameters:

- Harmonic variance: `a_dom²/2 = 21.81²/2 ≈ 237.8`
- AR(1) noise variance (by construction of the cascade): `≈ 1700.7`
- Trend variance over 254 steps (`trend_slope=-0.1873`/step, linear):
  `(254×0.1873)²/12 ≈ 188.6`
- **Deterministic share: `(188.6 + 237.8) / (188.6 + 237.8 + 1700.7) ≈ 0.21`**

That ≈0.21 theoretical floor lines up with the empirically observed
0.20–0.44 range (5-seed check above) — the empirical numbers run a bit
higher because `compare_io.py` averages ~8–9 frames per grid row (30 rows
over 254 frames), and averaging suppresses independent per-frame noise
more than it suppresses the shared, slowly-varying deterministic
component.

**So: getting time-profile r much above ~0.3–0.4 against an independent
realization of this passport would require the model to have much less
random noise than it actually specifies** (`std_dev`/AR(1) terms in
`code3.json` dominate the fluctuation by design, ~88% of its variance) —
it's not something a faster or more precise `andrey_hammer` could achieve.

## Status

**Fixed and verified**, committed to `andrey_hammer/src/andrey_hammer.c`.
