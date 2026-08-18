#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <time.h>
#include <unistd.h>
#include <signal.h>
#include <sys/mman.h>

/*
 * andrey_hammer — real-time JIT memory load simulator driven by Andrey's
 * compressed statistical model of a DAMON access trace.
 *
 * Pipeline position:
 *
 *   real damon.data (io format)
 *         │  (confidential fitting script, not part of this repo)
 *         ▼
 *   code3.json (10-channel "passport") + meta.json (geometry)
 *         │  <── THIS PROGRAM reads exactly these two files
 *         ▼
 *   live memory accesses, right now, paced in real time
 *         │  (an independent `damo record` watches this process)
 *         ▼
 *   fresh damon.data (io format) — compare against the original
 *
 * Design notes:
 *  - This process does NOT try to reuse the literal virtual addresses that
 *    were recorded in the original trace. Those addresses belong to a
 *    process that, by replay time, usually no longer exists -- and damo's
 *    own `replay` subcommand never maps the recorded addresses at all, it
 *    just uses them as dictionary keys into random heap objects, so an
 *    independent DAMON observer sees 0% spatial overlap with the original.
 *  - Instead, we mmap our OWN real, page-backed region sized from the
 *    compressed geometry (meta.matrix_geometry / physical_bounds), and
 *    reproduce the model's per-bin access-rate profile as literal byte
 *    writes to literal pages inside it, at the wall-clock cadence the
 *    passport implies. Whatever DAMON observes on THIS region is real,
 *    externally-verifiable memory traffic — not a replay artifact.
 *  - The model itself (Super-Gaussian 3-mode spatial mixture, cascaded
 *    AR(1) temporal fluctuation with split-normal innovations + harmonic +
 *    outliers) is a direct C port of generate.py (1).txt, the repo root's
 *    Python reference implementation. See that file for the derivation
 *    notes.
 */

/* ════════════════════════════════════════════════════════════════════════
   Minimal JSON parser (objects/arrays/strings/numbers only) — kept inline
   here rather than pulled from a shared header, to keep this a single,
   dependency-free translation unit.
   ════════════════════════════════════════════════════════════════════════ */

typedef enum { J_STR, J_NUM, J_OBJ, J_ARR, J_BOOL, J_NULL } jtype_t;

typedef struct jval {
    jtype_t type;
    union {
        char   *s;
        double  n;
        int     b;
        struct { char **keys; struct jval **vals; int cnt; } obj;
        struct { struct jval **items; int cnt; }              arr;
    };
} jval_t;

static const char *jskip(const char *p) {
    while (*p && isspace((unsigned char)*p)) p++;
    return p;
}
static jval_t *jnew(jtype_t t) { jval_t *v = calloc(1, sizeof(*v)); v->type = t; return v; }
static jval_t *jparse(const char **pp);

static jval_t *jparse_str(const char **pp) {
    const char *p = *pp + 1;
    const char *end = p;
    while (*end && *end != '"') { if (*end == '\\') end++; end++; }
    jval_t *v = jnew(J_STR);
    v->s = strndup(p, end - p);
    *pp = *end ? end + 1 : end;
    return v;
}
static jval_t *jparse_num(const char **pp) {
    char *end;
    double n = strtod(*pp, &end);
    jval_t *v = jnew(J_NUM); v->n = n;
    *pp = end;
    return v;
}
static jval_t *jparse_obj(const char **pp) {
    const char *p = jskip(*pp + 1);
    jval_t *v = jnew(J_OBJ);
    int cap = 8;
    v->obj.keys = malloc(cap * sizeof(char *));
    v->obj.vals = malloc(cap * sizeof(jval_t *));
    while (*p && *p != '}') {
        p = jskip(p);
        if (*p != '"') break;
        jval_t *key = jparse_str(&p);
        p = jskip(p);
        if (*p == ':') p++;
        p = jskip(p);
        jval_t *val = jparse(&p);
        if (v->obj.cnt == cap) {
            cap *= 2;
            v->obj.keys = realloc(v->obj.keys, cap * sizeof(char *));
            v->obj.vals = realloc(v->obj.vals, cap * sizeof(jval_t *));
        }
        v->obj.keys[v->obj.cnt] = key->s; key->s = NULL; free(key);
        v->obj.vals[v->obj.cnt] = val;
        v->obj.cnt++;
        p = jskip(p);
        if (*p == ',') p++;
    }
    *pp = *p ? p + 1 : p;
    return v;
}
static jval_t *jparse_arr(const char **pp) {
    const char *p = jskip(*pp + 1);
    jval_t *v = jnew(J_ARR);
    int cap = 8;
    v->arr.items = malloc(cap * sizeof(jval_t *));
    while (*p && *p != ']') {
        p = jskip(p);
        if (*p == ']') break;
        jval_t *item = jparse(&p);
        if (v->arr.cnt == cap) {
            cap *= 2;
            v->arr.items = realloc(v->arr.items, cap * sizeof(jval_t *));
        }
        v->arr.items[v->arr.cnt++] = item;
        p = jskip(p);
        if (*p == ',') p++;
    }
    *pp = *p ? p + 1 : p;
    return v;
}
static jval_t *jparse(const char **pp) {
    const char *p = jskip(*pp);
    if (*p == '"') { *pp = p; return jparse_str(pp); }
    if (*p == '{') { *pp = p; return jparse_obj(pp); }
    if (*p == '[') { *pp = p; return jparse_arr(pp); }
    if (*p == 't') { *pp = p + 4; jval_t *v = jnew(J_BOOL); v->b = 1; return v; }
    if (*p == 'f') { *pp = p + 5; jval_t *v = jnew(J_BOOL); v->b = 0; return v; }
    if (*p == 'n') { *pp = p + 4; return jnew(J_NULL); }
    if (*p == '-' || isdigit((unsigned char)*p)) { *pp = p; return jparse_num(pp); }
    *pp = p + 1;
    return jnew(J_NULL);
}
static jval_t *jget(jval_t *obj, const char *key) {
    if (!obj || obj->type != J_OBJ) return NULL;
    for (int i = 0; i < obj->obj.cnt; i++)
        if (strcmp(obj->obj.keys[i], key) == 0) return obj->obj.vals[i];
    return NULL;
}
static double jnum(jval_t *v, double def) { return (v && v->type == J_NUM) ? v->n : def; }
static jval_t *jload(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); exit(1); }
    fseek(f, 0, SEEK_END); long sz = ftell(f); rewind(f);
    char *buf = malloc(sz + 1);
    if (fread(buf, 1, sz, f) != (size_t)sz) { fprintf(stderr, "short read: %s\n", path); exit(1); }
    buf[sz] = '\0'; fclose(f);
    const char *p = buf;
    jval_t *v = jparse(&p);
    free(buf);
    return v;
}

/* Parses either a JSON number or a hex/decimal string ("0x...", "123") into
   a byte address/count. Dies with a clear message if the value is absent —
   deliberately no silent fallback, mirroring the Python modules' strict mode. */
static int jval_as_u64(jval_t *v, uint64_t *out) {
    if (!v) return 0;
    if (v->type == J_NUM) { *out = (uint64_t)v->n; return 1; }
    if (v->type == J_STR) { *out = strtoull(v->s, NULL, 0); return 1; }
    return 0;
}

/* ════════════════════════════════════════════════════════════════════════
   RNG — Box-Muller normal + uniform, seeded independently of Python.
   The model's statistical *shape* is what's being ported, not a bit-exact
   random stream; --seed only guarantees reproducibility across runs of
   THIS binary.
   ════════════════════════════════════════════════════════════════════════ */

typedef struct { unsigned int seed; double spare; int has_spare; } rng_t;

static double rng_uniform(rng_t *r) {
    return ((double)rand_r(&r->seed) + 1.0) / ((double)RAND_MAX + 2.0); /* open interval */
}
static double rng_normal(rng_t *r) {
    if (r->has_spare) { r->has_spare = 0; return r->spare; }
    double u1, u2, s;
    do {
        u1 = 2.0 * rng_uniform(r) - 1.0;
        u2 = 2.0 * rng_uniform(r) - 1.0;
        s = u1 * u1 + u2 * u2;
    } while (s >= 1.0 || s == 0.0);
    double mul = sqrt(-2.0 * log(s) / s);
    r->spare = u2 * mul; r->has_spare = 1;
    return u1 * mul;
}
static double clampd(double x, double lo, double hi) { return x < lo ? lo : (x > hi ? hi : x); }

/* ════════════════════════════════════════════════════════════════════════
   Passport channel model — one of {w1,mu1,sigma1, w2,mu2,sigma2,
   w3,mu3,sigma3, M_raw}. Precomputed constants + running filter state.
   ════════════════════════════════════════════════════════════════════════ */

typedef struct {
    /* precomputed from the passport, fixed for the whole run */
    double k, b, sigma_x, f_dom, a_dom, phi_start, outlier_rate;
    double phi_v, phi_z, alpha, mu_eps, std_z, scale_factor, theo_fluct_std;
    double outlier_mean, outlier_std, outlier_skewness;
    /* running AR(1) cascade state */
    double v_state, z_state;
} channel_t;

static const char *CHANNEL_KEYS[10] = {
    "w1", "mu1", "sigma1", "w2", "mu2", "sigma2", "w3", "mu3", "sigma3", "M_raw"
};
enum { W1 = 0, MU1, SIGMA1, W2, MU2, SIGMA2, W3, MU3, SIGMA3, M_RAW };

static int is_weight_idx(int p) { return p == W1 || p == W2 || p == W3; }
static int is_center_idx(int p) { return p == MU1 || p == MU2 || p == MU3; }
static int is_width_idx(int p)  { return p == SIGMA1 || p == SIGMA2 || p == SIGMA3; }

static double jreq(jval_t *obj, const char *key, const char *ctx) {
    jval_t *v = jget(obj, key);
    if (!v || v->type != J_NUM) {
        fprintf(stderr, "[FATAL] passport channel '%s' missing required key '%s'\n", ctx, key);
        exit(1);
    }
    return v->n;
}

static void channel_precompute(channel_t *c, jval_t *m, const char *ctx, double dt) {
    double trend_slope     = jreq(m, "trend_slope", ctx);
    double trend_intercept = jreq(m, "trend_intercept", ctx);
    double std_dev         = jreq(m, "std_dev", ctx);
    double skewness        = jreq(m, "skewness", ctx);
    double f_dom           = jreq(m, "f_dom", ctx);
    double a_dom           = jreq(m, "a_dom", ctx);
    double phi_start       = jreq(m, "phi_start", ctx);
    double outlier_rate    = jnum(jget(m, "outlier_rate"), 0.0) * dt;
    double rho_0           = jnum(jget(m, "autocorrelation_lag1"), 0.8);

    c->k = trend_slope * dt;
    c->b = trend_intercept;
    c->sigma_x = std_dev;
    c->f_dom = f_dom;
    c->a_dom = a_dom;
    c->phi_start = phi_start;
    c->outlier_rate = outlier_rate;
    c->outlier_mean = jnum(jget(m, "outlier_mean"), 0.0);
    c->outlier_std  = jnum(jget(m, "outlier_std"), 0.0);
    c->outlier_skewness = jnum(jget(m, "outlier_skewness"), 0.0);

    double lam = -log(clampd(rho_0, 1e-4, 0.9999));
    double phi_v = exp(-lam * dt);
    double phi_z = exp(-lam * dt);
    c->phi_v = phi_v;
    c->phi_z = phi_z;

    double alpha = clampd(skewness * 0.5, -0.9, 0.9);
    c->alpha = alpha;
    c->mu_eps = alpha * sqrt(2.0 / M_PI);

    double s2 = 1.0 + (alpha * alpha) * (1.0 - 2.0 / M_PI);
    double denom1 = fmax(1e-12, 1.0 - phi_v * phi_v);
    double denom2 = fmax(1e-12, 1.0 - phi_z * phi_z);
    double denom3 = fmax(1e-12, 1.0 - phi_v * phi_z);
    double var_z = (dt * dt * s2 * (1.0 + phi_v * phi_z)) / (denom1 * denom2 * denom3);
    c->std_z = sqrt(var_z);

    double num_val = dt * lam - 1.0 + exp(-dt * lam);
    double den_val = lam - 1.0 + exp(-lam);
    c->scale_factor = sqrt((num_val / (dt * dt)) / fmax(1e-12, den_val));

    double var_harmonic = (a_dom * a_dom) / 2.0;
    double var_tot = var_harmonic + (c->sigma_x * c->scale_factor) * (c->sigma_x * c->scale_factor);
    c->theo_fluct_std = var_tot > 1e-6 ? sqrt(var_tot) : 1e-6;

    c->v_state = 0.0;
    c->z_state = 0.0;
}

/* One time step of one channel → raw (pre-normalization) scalar value. */
static double channel_step(channel_t *c, rng_t *rng, double t_idx, double t_curr, double dt) {
    double xi = rng_normal(rng);
    double eps_raw = xi >= 0.0 ? xi * (1.0 + c->alpha) : xi * (1.0 - c->alpha);
    double epsilon = eps_raw - c->mu_eps;

    c->v_state = c->phi_v * c->v_state + epsilon;
    c->z_state = c->phi_z * c->z_state + dt * c->v_state;
    double z_scaled = c->z_state / c->std_z;

    double trend = c->b + c->k * t_idx;
    double harmonic = c->a_dom * cos(2.0 * M_PI * c->f_dom * t_curr + c->phi_start);

    double raw_fluct = harmonic + (c->sigma_x * c->scale_factor) * z_scaled;
    double fluct_clean = (raw_fluct / c->theo_fluct_std) * c->sigma_x;
    double X_raw = trend + fluct_clean;

    if (c->outlier_rate > 0.0 && rng_uniform(rng) < clampd(c->outlier_rate, 0.0, 1.0)) {
        double xi_out = rng_normal(rng);
        double alpha_out = clampd(c->outlier_skewness * 0.5, -0.9, 0.9);
        double eps_out_raw = xi_out >= 0.0 ? xi_out * (1.0 + alpha_out) : xi_out * (1.0 - alpha_out);
        double mu_out = alpha_out * sqrt(2.0 / M_PI);
        double var_out = 1.0 + (alpha_out * alpha_out) * (1.0 - 2.0 / M_PI);
        double eps_out_clean = (eps_out_raw - mu_out) / sqrt(var_out);

        double outlier_val = c->outlier_mean + c->outlier_std * eps_out_clean;
        double thresh = 3.0 * (c->sigma_x * c->scale_factor);
        if (c->outlier_mean > 0) outlier_val = fmax(outlier_val, thresh);
        else if (c->outlier_mean < 0) outlier_val = fmin(outlier_val, -thresh);
        X_raw += outlier_val;
    }
    return X_raw;
}

/* ════════════════════════════════════════════════════════════════════════
   Geometry / meta.json helpers — mirrors format_raw.py / simulate.py.
   ════════════════════════════════════════════════════════════════════════ */

static uint64_t get_address_span(jval_t *meta) {
    jval_t *phys = jget(meta, "physical_bounds");
    jval_t *geom = jget(meta, "matrix_geometry");

    jval_t *start_v = (phys && jget(phys, "active_min_addr")) ? jget(phys, "active_min_addr")
                     : jget(meta, "start_addr") ? jget(meta, "start_addr")
                     : geom ? jget(geom, "start_addr") : NULL;
    jval_t *end_v   = (phys && jget(phys, "active_max_addr")) ? jget(phys, "active_max_addr")
                     : jget(meta, "end_addr") ? jget(meta, "end_addr")
                     : geom ? jget(geom, "end_addr") : NULL;

    uint64_t start_addr, end_addr;
    if (!jval_as_u64(start_v, &start_addr) || !jval_as_u64(end_v, &end_addr)) {
        fprintf(stderr, "[FATAL] meta.json is missing address bounds "
                        "(expected 'physical_bounds.active_min_addr/active_max_addr' "
                        "or 'start_addr'/'end_addr')\n");
        exit(1);
    }
    if (end_addr <= start_addr) {
        fprintf(stderr, "[FATAL] meta.json end address must be greater than start address\n");
        exit(1);
    }
    const uint64_t PAGE = 4096;
    start_addr = (start_addr / PAGE) * PAGE;
    end_addr   = ((end_addr + PAGE - 1) / PAGE) * PAGE;
    return end_addr - start_addr; /* only the SPAN matters — see file header */
}

static double get_frame_dt_ms(jval_t *meta, long rows, double dt_ratio) {
    jval_t *tb_ms = jget(meta, "time_bounds_ms");
    jval_t *tb_us = jget(meta, "time_bounds_us");
    double start_ms, end_ms;
    if (tb_ms) {
        start_ms = jreq(tb_ms, "start_ms", "time_bounds_ms");
        end_ms   = jreq(tb_ms, "end_ms", "time_bounds_ms");
    } else if (tb_us) {
        start_ms = jreq(tb_us, "start_us", "time_bounds_us") / 1000.0;
        end_ms   = jreq(tb_us, "end_us", "time_bounds_us") / 1000.0;
    } else {
        fprintf(stderr, "[FATAL] meta.json is missing 'time_bounds_ms' or 'time_bounds_us'\n");
        exit(1);
    }
    double baseline_dt_ms = (end_ms - start_ms) / (double)rows;
    return baseline_dt_ms * dt_ratio;
}

/* ════════════════════════════════════════════════════════════════════════
   main
   ════════════════════════════════════════════════════════════════════════ */

static volatile sig_atomic_t g_running = 1;
static volatile sig_atomic_t g_go = 0;
static void on_sigint(int s) { (void)s; g_running = 0; }
static void on_usr1(int s)   { (void)s; g_go = 1; }

static uint64_t ts_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}
static void sleep_ns(long n) {
    if (n <= 0) return;
    struct timespec ts = { .tv_sec = n / 1000000000L, .tv_nsec = n % 1000000000L };
    clock_nanosleep(CLOCK_MONOTONIC, 0, &ts, NULL);
}

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [--auto] passport.json meta.json [gt.log]\n"
        "           [--seed N] [--steps N] [--extrapolation-factor F]\n"
        "           [--time-step-ratio R] [--legacy-clip]\n", prog);
}

int main(int argc, char **argv) {
    int auto_mode = 0;
    const char *passport_path = NULL, *meta_path = NULL, *gt_path = "/tmp/andrey_gt.log";
    unsigned int seed = 0;
    long steps_override = -1;
    double extrapolation_factor = 1.0, dt = 1.0;
    int legacy_clip = 0;
    const char *positional[3]; int npos = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--auto")) auto_mode = 1;
        else if (!strcmp(argv[i], "--seed") && i + 1 < argc) seed = (unsigned)atoi(argv[++i]);
        else if (!strcmp(argv[i], "--steps") && i + 1 < argc) steps_override = atol(argv[++i]);
        else if (!strcmp(argv[i], "--extrapolation-factor") && i + 1 < argc) extrapolation_factor = atof(argv[++i]);
        else if (!strcmp(argv[i], "--time-step-ratio") && i + 1 < argc) dt = atof(argv[++i]);
        else if (!strcmp(argv[i], "--legacy-clip")) legacy_clip = 1;
        else if (argv[i][0] == '-') { usage(argv[0]); return 1; }
        else if (npos < 3) positional[npos++] = argv[i];
    }
    if (npos < 2) { usage(argv[0]); return 1; }
    passport_path = positional[0];
    meta_path     = positional[1];
    if (npos == 3) gt_path = positional[2];

    jval_t *meta     = jload(meta_path);
    jval_t *passport = jload(passport_path);

    jval_t *geom = jget(meta, "matrix_geometry");
    if (!geom) { fprintf(stderr, "[FATAL] meta.json missing 'matrix_geometry'\n"); return 1; }
    long cols = (long)jreq(geom, "cols", "matrix_geometry");
    long rows = (long)jreq(geom, "rows", "matrix_geometry");
    if (cols <= 0 || rows <= 0) { fprintf(stderr, "[FATAL] matrix_geometry.cols/rows must be > 0\n"); return 1; }

    double p_shape = jreq(meta, "super_gaussian_p", "meta");

    uint64_t total_bytes = get_address_span(meta);
    double frame_dt_ms = get_frame_dt_ms(meta, rows, dt);

    long t_sim = steps_override > 0 ? steps_override
                                     : (long)llround((double)rows * extrapolation_factor);
    if (t_sim < 1) t_sim = 1;

    /* Bin boundaries in BYTES, relative to our own region's base (offset 0) —
       page-aligned exactly like format_raw.py / simulate.py do for the
       original absolute addresses. We only need proportions, not the
       original absolute location (see file header). */
    uint64_t *bin_boundaries = malloc((cols + 1) * sizeof(uint64_t));
    for (long c = 0; c <= cols; c++) {
        double raw = ((double)c * (double)total_bytes) / (double)cols;
        bin_boundaries[c] = (uint64_t)llround(raw / 4096.0) * 4096ULL;
    }
    bin_boundaries[0] = 0;
    bin_boundaries[cols] = total_bytes;

    /* ── mmap our own real region, sized from the compressed geometry ──── */
    void *region = mmap(NULL, total_bytes, PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (region == MAP_FAILED) { perror("mmap"); return 1; }
    for (uint64_t off = 0; off < total_bytes; off += 4096)
        *((volatile char *)region + off) = 0; /* prefault */
    size_t n_pages = total_bytes / 4096;

    /* ── load & precompute the 10-channel passport ──────────────────────── */
    channel_t channels[10];
    for (int p = 0; p < 10; p++) {
        jval_t *m = jget(passport, CHANNEL_KEYS[p]);
        if (!m) { fprintf(stderr, "[FATAL] passport missing channel '%s'\n", CHANNEL_KEYS[p]); return 1; }
        channel_precompute(&channels[p], m, CHANNEL_KEYS[p], dt);
    }

    double norm_const = p_shape / (pow(2.0, 1.0 + 1.0 / p_shape) * tgamma(1.0 / p_shape));

    rng_t rng = { .seed = seed ? seed : 1, .spare = 0, .has_spare = 0 };

    /* ── announce ourselves (markers run_andrey.sh parses: PID/REGION/READY) ── */
    printf("# PID=%d\n", getpid());
    printf("# REGION 0 0x%lx 0x%lx\n", (unsigned long)region, (unsigned long)region + total_bytes);
    printf("PID:      %d\n", getpid());
    printf("Region:   %p-%p  (%zu pages, %.1f KiB)\n",
           region, (char *)region + total_bytes, n_pages, total_bytes / 1024.0);
    printf("Geometry: cols=%ld rows=%ld p_shape=%.2f frame=%.3f ms  steps=%ld\n",
           cols, rows, p_shape, frame_dt_ms, t_sim);
    fflush(stdout);

    signal(SIGINT, on_sigint);
    if (auto_mode) {
        signal(SIGUSR1, on_usr1);
        printf("# READY\n"); fflush(stdout);
        while (!g_go) pause();
        printf("GO\n"); fflush(stdout);
    } else {
        printf("\nSet up DAMON monitoring, then press Enter to start...\n");
        getchar();
    }

    FILE *gt = fopen(gt_path, "w");
    if (!gt) { perror(gt_path); return 1; }
    fprintf(gt, "# region 0 base=0x%lx pages=%zu\n", (unsigned long)region, n_pages);
    fprintf(gt, "# ts_ns region page\n");

    /* Frame boundary log — the ACTUAL wall-clock start/end of each frame
       (after padding), not the nominal frame_dt_ms. gt_to_io.py bins gt.log
       touches by these real windows instead of assuming perfect pacing, so
       an io-format file built from this reflects what andrey_hammer truly
       did rather than what it was supposed to do. Also makes the pacing
       drift measurable directly (end-start vs nominal frame_dt_ms). */
    char frames_path[4160];
    snprintf(frames_path, sizeof(frames_path), "%s.frames", gt_path);
    FILE *frames_f = fopen(frames_path, "w");
    if (!frames_f) { perror(frames_path); return 1; }
    fprintf(frames_f, "# frame_idx start_ns end_ns nominal_dt_ms\n");

    double *profile = malloc(cols * sizeof(double));
    long *row_accesses = malloc(cols * sizeof(long));
    size_t sched_cap = 4096;
    long *sched = malloc(sched_cap * sizeof(long));

    long total_frames = 0;
    uint64_t total_touches = 0;
    long counter = 0;

    for (long t_idx = 0; t_idx < t_sim && g_running; t_idx++) {
        uint64_t frame_start = ts_ns();
        double t_curr = (double)t_idx * dt;

        double chan_val[10];
        for (int p = 0; p < 10; p++) {
            double X_raw = channel_step(&channels[p], &rng, (double)t_idx, t_curr, dt);
            if (is_weight_idx(p))      chan_val[p] = clampd(X_raw, 0.0, 1.0);
            else if (is_center_idx(p)) chan_val[p] = clampd(X_raw, 0.0, (double)cols);
            else if (is_width_idx(p))  chan_val[p] = clampd(X_raw, 0.5, (double)cols / 2.0);
            else /* M_raw */           chan_val[p] = legacy_clip ? clampd(X_raw, 0.0, (double)cols * 9.0)
                                                                  : fmax(X_raw, 0.0);
        }

        double w_sum = fmax(chan_val[W1] + chan_val[W2] + chan_val[W3], 1e-12);
        double w1 = chan_val[W1] / w_sum, mu1 = chan_val[MU1], sig1 = chan_val[SIGMA1];
        double w2 = chan_val[W2] / w_sum, mu2 = chan_val[MU2], sig2 = chan_val[SIGMA2];
        double w3 = chan_val[W3] / w_sum, mu3 = chan_val[MU3], sig3 = chan_val[SIGMA3];
        double M_raw = chan_val[M_RAW];

        double modes_w[3] = { w1, w2, w3 };
        double modes_mu[3] = { mu1, mu2, mu3 };
        double modes_sig[3] = { sig1, sig2, sig3 };

        double prof_sum = 0.0;
        for (long x = 0; x < cols; x++) profile[x] = 0.0;
        for (int k = 0; k < 3; k++) {
            double sig_safe = fmax(modes_sig[k], 0.5);
            double pdf_norm = norm_const / sig_safe;
            for (long x = 0; x < cols; x++) {
                double exponent = -0.5 * pow(fabs((double)x - modes_mu[k]) / sig_safe, p_shape);
                profile[x] += modes_w[k] * (pdf_norm * exp(exponent));
            }
        }
        for (long x = 0; x < cols; x++) prof_sum += profile[x];
        if (prof_sum > 0.0)
            for (long x = 0; x < cols; x++) profile[x] = (profile[x] / prof_sum) * M_raw;

        long frame_total = 0;
        for (long x = 0; x < cols; x++) {
            long acc = (long)llround(profile[x]);
            if (acc < 0) acc = 0;
            row_accesses[x] = acc;
            frame_total += acc;
        }

        /* Build a shuffled bin schedule so accesses land spread across the
           frame's real duration rather than bursting bin-by-bin. */
        if ((size_t)frame_total > sched_cap) {
            sched_cap = (size_t)frame_total * 2;
            sched = realloc(sched, sched_cap * sizeof(long));
        }
        long si = 0;
        for (long x = 0; x < cols; x++)
            for (long r = 0; r < row_accesses[x]; r++) sched[si++] = x;
        for (long i = si - 1; i > 0; i--) {
            long j = rand_r(&rng.seed) % (i + 1);
            long tmp = sched[i]; sched[i] = sched[j]; sched[j] = tmp;
        }

        if (si > 0) {
            /* Absolute-target pacing instead of "sleep interval_ns after every
               touch": touch i is scheduled for frame_start + i*interval_ns, and
               we only sleep the actual remaining gap to that target -- never a
               fixed relative amount. This is self-correcting: clock_nanosleep()
               overshoots its requested duration by ~87us on average under WSL2
               (measured -- see PACING_DRIFT_ISSUE.md), and with a fixed
               relative interval that overshoot compounds every single call
               (99.4% of a frame's runtime ends up inside sleep_ns() as a
               result). Targeting an absolute schedule means a touch that's
               already at or past its target skips sleeping entirely instead of
               sleeping interval_ns anyway -- the overshoot from previous calls
               gets absorbed instead of stacking on top of the next one, and
               busy frames end up issuing fewer sleep calls exactly when they'd
               otherwise be accumulating the most error. */
            long interval_ns = (long)((frame_dt_ms * 1e6) / (double)si);
            uint64_t next_target = frame_start;
            for (long i = 0; i < si && g_running; i++) {
                next_target += (uint64_t)interval_ns;

                long bin = sched[i];
                uint64_t bin_lo = bin_boundaries[bin], bin_hi = bin_boundaries[bin + 1];
                size_t bin_pages = (bin_hi > bin_lo) ? (bin_hi - bin_lo) / 4096 : 0;
                uint64_t off = bin_pages > 0
                    ? bin_lo + (uint64_t)(rand_r(&rng.seed) % bin_pages) * 4096
                    : bin_lo;
                if (off >= total_bytes) off = total_bytes - 4096;

                *((volatile char *)region + off) = (char)(counter++ & 0xFF);
                fprintf(gt, "%llu 0 %llu\n", (unsigned long long)ts_ns(),
                        (unsigned long long)(off / 4096));

                uint64_t now = ts_ns();
                if (now < next_target) {
                    long gap_ns = (long)(next_target - now);
                    if (gap_ns > 50000) sleep_ns(gap_ns);
                }
                /* else: already at or past schedule -- skip sleeping instead
                   of blindly sleeping interval_ns, so debt doesn't compound. */
            }
        }

        long elapsed_ns = (long)(ts_ns() - frame_start);
        long remaining_ns = (long)(frame_dt_ms * 1e6) - elapsed_ns;
        sleep_ns(remaining_ns);

        uint64_t frame_end = ts_ns();
        fprintf(frames_f, "%ld %llu %llu %.3f\n", t_idx,
                (unsigned long long)frame_start, (unsigned long long)frame_end, frame_dt_ms);

        total_frames++;
        total_touches += (uint64_t)frame_total;
    }

    fflush(gt);
    fclose(gt);
    fflush(frames_f);
    fclose(frames_f);
    printf("Total: %ld frames, %llu accesses simulated in real time\n",
           total_frames, (unsigned long long)total_touches);
    printf("Frame boundaries: %s\n", frames_path);

    free(sched); free(profile); free(row_accesses); free(bin_boundaries);
    munmap(region, total_bytes);
    return 0;
}
