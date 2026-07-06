#pragma once
#include "region.h"
#include "spatial.h"
#include "temporal.h"
#include "gt_log.h"
#include <pthread.h>
#include <time.h>

typedef struct {
    region_t   *region;
    int         region_idx;
    spatial_t  *spatial;
    temporal_t *temporal;
    gt_log_t   *gt_log;
    double      start_sec;
    double      end_sec;

    /* runtime */
    struct timespec t0;
    pthread_t       thread;
    _Atomic int     stop;
    long            access_count;
} track_t;

track_t *track_create(region_t *r, int region_idx, spatial_t *sp, temporal_t *tp,
                      gt_log_t *gl, double start_sec, double end_sec);
void track_start(track_t *t, struct timespec *t0);
void track_stop(track_t *t);
void track_join(track_t *t);
void track_free(track_t *t);
