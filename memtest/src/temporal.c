#define _GNU_SOURCE
#include "temporal.h"
#include <stdlib.h>
#include <math.h>
#include <string.h>

static void default_destroy(temporal_t *self) { free(self->params); free(self); }

/* ── CONST ─────────────────────────────────────────────────────────────── */
typedef struct { double hz; } const_p;

static double const_eval(temporal_t *self, double t) {
    (void)t; return ((const_p *)self->params)->hz;
}

temporal_t *temporal_const(double hz) {
    temporal_t *t = calloc(1, sizeof(*t));
    const_p *p = malloc(sizeof(*p)); p->hz = hz;
    t->eval = const_eval; t->destroy = default_destroy; t->params = p;
    return t;
}

/* ── SINE ───────────────────────────────────────────────────────────────── */
typedef struct { double base, amp, period, phase; } sine_p;

static double sine_eval(temporal_t *self, double t) {
    sine_p *p = self->params;
    double hz = p->base + p->amp * sin(2.0 * M_PI * t / p->period + p->phase);
    return hz < 0.0 ? 0.0 : hz;
}

temporal_t *temporal_sine(double base, double amp, double period, double phase) {
    temporal_t *t = calloc(1, sizeof(*t));
    sine_p *p = malloc(sizeof(*p));
    p->base = base; p->amp = amp; p->period = period; p->phase = phase;
    t->eval = sine_eval; t->destroy = default_destroy; t->params = p;
    return t;
}

/* ── SQUARE ─────────────────────────────────────────────────────────────── */
typedef struct { double on_hz, duty, period, phase; } square_p;

static double square_eval(temporal_t *self, double t) {
    square_p *p = self->params;
    double phase_sec = p->phase / (2.0 * M_PI) * p->period;
    return fmod(t + phase_sec, p->period) / p->period < p->duty ? p->on_hz : 0.0;
}

temporal_t *temporal_square(double on_hz, double duty, double period, double phase_rad) {
    temporal_t *t = calloc(1, sizeof(*t));
    square_p *p = malloc(sizeof(*p));
    p->on_hz = on_hz; p->duty = duty; p->period = period; p->phase = phase_rad;
    t->eval = square_eval; t->destroy = default_destroy; t->params = p;
    return t;
}

/* ── RAMP ───────────────────────────────────────────────────────────────── */
typedef struct { double start, end, total; } ramp_p;

static double ramp_eval(temporal_t *self, double t) {
    ramp_p *p = self->params;
    double r = t / p->total;
    if (r < 0.0) r = 0.0;
    if (r > 1.0) r = 1.0;
    return p->start + (p->end - p->start) * r;
}

temporal_t *temporal_ramp(double start, double end, double total) {
    temporal_t *t = calloc(1, sizeof(*t));
    ramp_p *p = malloc(sizeof(*p));
    p->start = start; p->end = end; p->total = total;
    t->eval = ramp_eval; t->destroy = default_destroy; t->params = p;
    return t;
}

/* ── STEPS ──────────────────────────────────────────────────────────────── */
typedef struct { step_t *steps; int n; } steps_p;

static double steps_eval(temporal_t *self, double t) {
    steps_p *p = self->params;
    double elapsed = 0.0;
    for (int i = 0; i < p->n; i++) {
        elapsed += p->steps[i].duration_sec;
        if (t < elapsed) return p->steps[i].hz;
    }
    return p->steps[p->n - 1].hz;
}

static void steps_destroy(temporal_t *self) {
    steps_p *p = self->params; free(p->steps); free(p); free(self);
}

temporal_t *temporal_steps(step_t *steps, int n) {
    temporal_t *t = calloc(1, sizeof(*t));
    steps_p *p = malloc(sizeof(*p));
    p->steps = malloc(n * sizeof(step_t));
    memcpy(p->steps, steps, n * sizeof(step_t));
    p->n = n;
    t->eval = steps_eval; t->destroy = steps_destroy; t->params = p;
    return t;
}

void temporal_free(temporal_t *t) { if (t && t->destroy) t->destroy(t); }
