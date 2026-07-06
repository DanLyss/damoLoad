#include "gt_log.h"
#include <stdlib.h>

gt_log_t *gt_log_create(size_t capacity) {
    gt_log_t *l = malloc(sizeof(*l));
    l->buf      = malloc(capacity * sizeof(gt_entry_t));
    l->capacity = capacity;
    l->count    = 0;
    return l;
}

void gt_log_record(gt_log_t *log, uint64_t ts_ns, int region, int page) {
    size_t idx = __atomic_fetch_add(&log->count, 1, __ATOMIC_RELAXED);
    if (idx < log->capacity) {
        log->buf[idx].ts_ns  = ts_ns;
        log->buf[idx].region = region;
        log->buf[idx].page   = page;
    }
}

void gt_log_flush(gt_log_t *log, FILE *f) {
    size_t n = log->count < log->capacity ? log->count : log->capacity;
    fprintf(f, "# ts_ns region page\n");
    for (size_t i = 0; i < n; i++)
        fprintf(f, "%lu %d %d\n", (unsigned long)log->buf[i].ts_ns,
                log->buf[i].region, log->buf[i].page);
}

void gt_log_free(gt_log_t *log) {
    if (!log) return;
    free(log->buf);
    free(log);
}
