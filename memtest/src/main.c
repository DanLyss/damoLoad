#define _GNU_SOURCE
#include "workload.h"
#include "region.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>

static volatile sig_atomic_t g_ready = 0;
static void on_usr1(int sig) { (void)sig; g_ready = 1; }

int main(int argc, char *argv[]) {
    int auto_mode = 0;
    int argi = 1;

    if (argc > 1 && strcmp(argv[1], "--auto") == 0) {
        auto_mode = 1;
        argi = 2;
    }

    if (argc - argi < 1) {
        fprintf(stderr, "Usage: %s [--auto] workload.json [gt.log]\n", argv[0]);
        return 1;
    }

    const char *json_path = argv[argi];
    const char *gt_path   = (argc - argi > 1) ? argv[argi + 1] : "/tmp/gt.log";

    workload_t *w = workload_load(json_path);
    if (!w) return 1;

    /* machine-parseable lines (read by run_memtest.sh) */
    printf("# PID=%d\n", getpid());
    for (int i = 0; i < w->n_regions; i++) {
        region_t *r = w->regions[i];
        printf("# REGION %d 0x%lx 0x%lx\n",
               i,
               (unsigned long)r->buf,
               (unsigned long)((char *)r->buf + r->size_bytes));
    }

    /* human-readable */
    printf("PID: %d\n", getpid());
    printf("Regions: %d\n", w->n_regions);
    for (int i = 0; i < w->n_regions; i++) {
        region_t *r = w->regions[i];
        printf("  [%d] %p-%p  (%zu pages, %zu KB)\n",
               i, r->buf, (char *)r->buf + r->size_bytes,
               r->n_pages, r->size_bytes / 1024);
    }
    printf("Tracks:   %d\n", w->n_tracks);
    printf("Duration: %.1f s\n", w->duration_sec);

    if (auto_mode) {
        signal(SIGUSR1, on_usr1);
        printf("# READY\n");
        fflush(stdout);
        while (!g_ready) pause();
        printf("GO\n");
        fflush(stdout);
    } else {
        printf("\nSet up DAMON monitoring, then press Enter to start...\n");
        getchar();
    }

    workload_run(w, gt_path);
    workload_free(w);
    return 0;
}
