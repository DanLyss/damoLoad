#pragma once

typedef struct temporal temporal_t;

struct temporal {
    double (*eval)(temporal_t *self, double t_sec); /* hz at local time t */
    void   (*destroy)(temporal_t *self);
    void   *params;
};

typedef struct { double hz; double duration_sec; } step_t;

temporal_t *temporal_const(double hz);
temporal_t *temporal_sine(double base_hz, double amplitude, double period_sec, double phase_rad);
temporal_t *temporal_square(double on_hz, double duty_ratio, double period_sec, double phase_rad);
temporal_t *temporal_ramp(double start_hz, double end_hz, double total_sec);
temporal_t *temporal_steps(step_t *steps, int n);

void temporal_free(temporal_t *t);
