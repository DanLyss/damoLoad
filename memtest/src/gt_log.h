#pragma once
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>

typedef struct { uint64_t ts_ns; int region; int page; } gt_entry_t;

typedef struct {
    gt_entry_t *buf;
    size_t      capacity;
    size_t      count; /* written with atomic fetch-add */
} gt_log_t;

gt_log_t *gt_log_create(size_t capacity);
void      gt_log_record(gt_log_t *log, uint64_t ts_ns, int region, int page);
void      gt_log_flush(gt_log_t *log, FILE *f);
void      gt_log_free(gt_log_t *log);
