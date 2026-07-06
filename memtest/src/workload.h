#pragma once
#include "region.h"
#include "track.h"
#include "gt_log.h"

#define MAX_REGIONS 512
#define MAX_TRACKS  1024

typedef struct {
    region_t  *regions[MAX_REGIONS];
    int        n_regions;
    gt_log_t  *gt_log;
    track_t   *tracks[MAX_TRACKS];
    int        n_tracks;
    double     duration_sec;
} workload_t;

workload_t *workload_load(const char *json_path);
void        workload_run(workload_t *w, const char *gt_path);
void        workload_free(workload_t *w);
