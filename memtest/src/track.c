#define _GNU_SOURCE
#include "track.h"
#include <stdlib.h>
#include <math.h>
#include <time.h>

static double ts_to_sec(const struct timespec *ts) {
    return ts->tv_sec + ts->tv_nsec * 1e-9;
}
static uint64_t ts_to_ns(const struct timespec *ts) {
    return (uint64_t)ts->tv_sec * 1000000000ULL + ts->tv_nsec;
}

static void *track_fn(void *arg) {
    track_t *t = arg;
    double t0  = ts_to_sec(&t->t0);

    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    double last_sec = ts_to_sec(&now);
    double debt_ns  = 0.0;

    while (!t->stop) {
        clock_gettime(CLOCK_MONOTONIC, &now);
        double now_sec  = ts_to_sec(&now);
        double elapsed  = (now_sec - last_sec) * 1e9;
        last_sec = now_sec;

        double t_abs = now_sec - t0;                 /* time since workload start */
        double t_loc = t_abs  - t->start_sec;        /* time since this track start */

        if (t_abs < t->start_sec || t_abs > t->end_sec) {
            struct timespec sl = {0, 1000000};
            nanosleep(&sl, NULL);
            debt_ns = 0.0;
            continue;
        }

        double hz = t->temporal->eval(t->temporal, t_loc);
        if (hz <= 0.0) {
            struct timespec sl = {0, 1000000};
            nanosleep(&sl, NULL);
            debt_ns = 0.0;
            continue;
        }

        double interval_ns = 1e9 / hz;
        debt_ns += elapsed;
        if (debt_ns > interval_ns * 10.0) debt_ns = interval_ns * 10.0; /* cap burst */

        while (debt_ns >= interval_ns) {
            int page = t->spatial->next(t->spatial, t_loc);

            if (page == -1) {
                /* spatial_all: touch every page in the region */
                clock_gettime(CLOCK_MONOTONIC, &now);
                uint64_t ts = ts_to_ns(&now);
                for (int pg = 0; pg < (int)t->region->n_pages; pg++) {
                    *((volatile char *)t->region->buf + (size_t)pg * 4096)
                        = (char)(t->access_count & 0xFF);
                    gt_log_record(t->gt_log, ts, t->region_idx, pg);
                    t->access_count++;
                }
            } else {
                *((volatile char *)t->region->buf + (size_t)page * 4096)
                    = (char)(t->access_count & 0xFF);
                clock_gettime(CLOCK_MONOTONIC, &now);
                gt_log_record(t->gt_log, ts_to_ns(&now), t->region_idx, page);
                t->access_count++;
            }

            debt_ns -= interval_ns;
        }

        long sleep_ns = (long)(interval_ns - debt_ns);
        if (sleep_ns > 50000) {
            struct timespec sl = {0, sleep_ns};
            nanosleep(&sl, NULL);
        }
    }
    return NULL;
}

track_t *track_create(region_t *r, int region_idx, spatial_t *sp, temporal_t *tp,
                      gt_log_t *gl, double start_sec, double end_sec) {
    track_t *t   = calloc(1, sizeof(*t));
    t->region     = r;
    t->region_idx = region_idx;
    t->spatial   = sp;
    t->temporal  = tp;
    t->gt_log    = gl;
    t->start_sec = start_sec;
    t->end_sec   = end_sec;
    return t;
}

void track_start(track_t *t, struct timespec *t0) {
    t->t0   = *t0;
    t->stop = 0;
    pthread_create(&t->thread, NULL, track_fn, t);
}

void track_stop(track_t *t) { t->stop = 1; }
void track_join(track_t *t) { pthread_join(t->thread, NULL); }
void track_free(track_t *t) { free(t); }
