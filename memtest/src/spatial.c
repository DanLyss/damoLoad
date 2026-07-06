#define _GNU_SOURCE
#include "spatial.h"
#include <stdlib.h>
#include <math.h>
#include <string.h>

/* ── UNIFORM ────────────────────────────────────────────────────────────── */
typedef struct { unsigned int seed; } uni_p;

static int uniform_next(spatial_t *self, double t) {
    (void)t;
    uni_p *p = self->params;
    return rand_r(&p->seed) % self->n_pages;
}
static void default_destroy(spatial_t *s) { free(s->params); free(s); }

spatial_t *spatial_uniform(int n_pages) {
    spatial_t *s = calloc(1, sizeof(*s));
    uni_p *p = malloc(sizeof(*p)); p->seed = (unsigned)rand();
    s->n_pages = n_pages; s->params = p;
    s->next = uniform_next; s->destroy = default_destroy;
    return s;
}

/* ── HOTSPOT ────────────────────────────────────────────────────────────── */
typedef struct { double *cdf; int n; unsigned int seed; } hot_p;

static int hotspot_next(spatial_t *self, double t) {
    (void)t;
    hot_p *p = self->params;
    double r = (double)rand_r(&p->seed) / RAND_MAX;
    for (int i = 0; i < p->n - 1; i++)
        if (r < p->cdf[i]) return i;
    return p->n - 1;
}
static void hot_destroy(spatial_t *s) {
    hot_p *p = s->params; free(p->cdf); free(p); free(s);
}

spatial_t *spatial_hotspot(int n_pages, int *hot_pages, int n_hot, double hot_ratio) {
    spatial_t *s = calloc(1, sizeof(*s));
    s->n_pages = n_pages;
    hot_p *p = malloc(sizeof(*p));
    p->cdf = calloc(n_pages, sizeof(double));
    p->n   = n_pages;
    p->seed = (unsigned)rand();

    int n_cold = n_pages - n_hot;
    double hot_per  = n_hot  > 0 ? hot_ratio          / n_hot  : 0.0;
    double cold_per = n_cold > 0 ? (1.0 - hot_ratio)  / n_cold : 0.0;

    double *prob = calloc(n_pages, sizeof(double));
    for (int i = 0; i < n_pages; i++) prob[i] = cold_per;
    for (int i = 0; i < n_hot;   i++) prob[hot_pages[i]] = hot_per;

    double cum = 0.0;
    for (int i = 0; i < n_pages; i++) { cum += prob[i]; p->cdf[i] = cum; }
    p->cdf[n_pages - 1] = 1.0;
    free(prob);

    s->params = p; s->next = hotspot_next; s->destroy = hot_destroy;
    return s;
}

/* ── SEQUENTIAL ─────────────────────────────────────────────────────────── */
typedef struct { long cursor; } seq_p;

static int sequential_next(spatial_t *self, double t) {
    (void)t;
    seq_p *p = self->params;
    return (int)(p->cursor++ % self->n_pages);
}

spatial_t *spatial_sequential(int n_pages) {
    spatial_t *s = calloc(1, sizeof(*s));
    seq_p *p = calloc(1, sizeof(*p));
    s->n_pages = n_pages; s->params = p;
    s->next = sequential_next; s->destroy = default_destroy;
    return s;
}

/* ── ZIPF ───────────────────────────────────────────────────────────────── */
typedef struct { double *cdf; int n; unsigned int seed; } zipf_p;

static int zipf_next(spatial_t *self, double t) {
    (void)t;
    zipf_p *p = self->params;
    double r = (double)rand_r(&p->seed) / RAND_MAX;
    for (int i = 0; i < p->n - 1; i++)
        if (r < p->cdf[i]) return i;
    return p->n - 1;
}
static void zipf_destroy(spatial_t *s) {
    zipf_p *p = s->params; free(p->cdf); free(p); free(s);
}

spatial_t *spatial_zipf(int n_pages, double s_exp) {
    spatial_t *s = calloc(1, sizeof(*s));
    s->n_pages = n_pages;
    zipf_p *p = malloc(sizeof(*p));
    p->n    = n_pages;
    p->cdf  = calloc(n_pages, sizeof(double));
    p->seed = (unsigned)rand();

    double norm = 0.0;
    for (int i = 1; i <= n_pages; i++) norm += 1.0 / pow((double)i, s_exp);

    double cum = 0.0;
    for (int i = 0; i < n_pages; i++) {
        cum += (1.0 / pow((double)(i + 1), s_exp)) / norm;
        p->cdf[i] = cum;
    }
    p->cdf[n_pages - 1] = 1.0;

    s->params = p; s->next = zipf_next; s->destroy = zipf_destroy;
    return s;
}

/* ── GAUSSIAN ───────────────────────────────────────────────────────────── */
typedef struct { double center, sigma; unsigned int seed; } gauss_p;

static int gaussian_next(spatial_t *self, double t) {
    (void)t;
    gauss_p *p = self->params;
    /* Box-Muller */
    double u1 = ((double)rand_r(&p->seed) + 1.0) / ((double)RAND_MAX + 2.0);
    double u2 = ((double)rand_r(&p->seed) + 1.0) / ((double)RAND_MAX + 2.0);
    double z  = sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
    int page  = (int)round(p->center + p->sigma * z);
    if (page < 0) page = 0;
    if (page >= self->n_pages) page = self->n_pages - 1;
    return page;
}

spatial_t *spatial_gaussian(int n_pages, double center, double sigma) {
    spatial_t *s = calloc(1, sizeof(*s));
    gauss_p *p = malloc(sizeof(*p));
    p->center = center; p->sigma = sigma; p->seed = (unsigned)rand();
    s->n_pages = n_pages; s->params = p;
    s->next = gaussian_next; s->destroy = default_destroy;
    return s;
}

/* ── ALL ────────────────────────────────────────────────────────────────── */
static int all_next(spatial_t *self, double t) { (void)self; (void)t; return -1; }
static void all_destroy(spatial_t *s) { free(s); }

spatial_t *spatial_all(int n_pages) {
    spatial_t *s = calloc(1, sizeof(*s));
    s->n_pages = n_pages;
    s->params  = NULL;
    s->next    = all_next;
    s->destroy = all_destroy;
    return s;
}

void spatial_free(spatial_t *s) { if (s && s->destroy) s->destroy(s); }
