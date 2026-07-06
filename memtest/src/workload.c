#define _GNU_SOURCE
#include "workload.h"
#include "region.h"
#include "spatial.h"
#include "temporal.h"
#include "track.h"
#include "gt_log.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <time.h>
#include <unistd.h>

/* ══════════════════════════════════════════════════════════════
   Minimal JSON parser — handles objects, arrays, strings, numbers
   ══════════════════════════════════════════════════════════════ */

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

static jval_t *jnew(jtype_t t) {
    jval_t *v = calloc(1, sizeof(*v)); v->type = t; return v;
}

static jval_t *jparse(const char **pp);

static jval_t *jparse_str(const char **pp) {
    const char *p = *pp + 1; /* skip opening " */
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
    const char *p = jskip(*pp + 1); /* skip '{' */
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
    const char *p = jskip(*pp + 1); /* skip '[' */
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
    if (*p == '"')      { *pp = p; return jparse_str(pp); }
    if (*p == '{')      { *pp = p; return jparse_obj(pp); }
    if (*p == '[')      { *pp = p; return jparse_arr(pp); }
    if (*p == 't')      { *pp = p+4; jval_t *v=jnew(J_BOOL); v->b=1; return v; }
    if (*p == 'f')      { *pp = p+5; jval_t *v=jnew(J_BOOL); v->b=0; return v; }
    if (*p == 'n')      { *pp = p+4; return jnew(J_NULL); }
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

static double jnum(jval_t *v, double def) {
    return (v && v->type == J_NUM) ? v->n : def;
}
static const char *jstr(jval_t *v) {
    return (v && v->type == J_STR) ? v->s : "";
}

static jval_t *jload(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) { perror(path); return NULL; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); rewind(f);
    char *buf = malloc(sz + 1);
    if (fread(buf, 1, sz, f) != (size_t)sz) { free(buf); fclose(f); return NULL; }
    buf[sz] = '\0'; fclose(f);
    const char *p = buf;
    jval_t *v = jparse(&p);
    free(buf);
    return v;
}

static void jfree(jval_t *v) {
    if (!v) return;
    if (v->type == J_STR)  { free(v->s); }
    else if (v->type == J_OBJ) {
        for (int i = 0; i < v->obj.cnt; i++) { free(v->obj.keys[i]); jfree(v->obj.vals[i]); }
        free(v->obj.keys); free(v->obj.vals);
    } else if (v->type == J_ARR) {
        for (int i = 0; i < v->arr.cnt; i++) jfree(v->arr.items[i]);
        free(v->arr.items);
    }
    free(v);
}

/* ══════════════════════════════════════════════════════════════
   Build spatial/temporal from JSON objects
   ══════════════════════════════════════════════════════════════ */

static temporal_t *build_temporal(jval_t *j, double track_dur) {
    const char *type = jstr(jget(j, "type"));
    if (strcmp(type, "const") == 0)
        return temporal_const(jnum(jget(j, "hz"), 100));
    if (strcmp(type, "sine") == 0)
        return temporal_sine(jnum(jget(j, "base_hz"), 50),
                             jnum(jget(j, "amplitude"), 30),
                             jnum(jget(j, "period_sec"), 2.0),
                             jnum(jget(j, "phase_rad"), 0.0));
    if (strcmp(type, "square") == 0)
        return temporal_square(jnum(jget(j, "on_hz"), 200),
                               jnum(jget(j, "duty"), 0.5),
                               jnum(jget(j, "period_sec"), 1.0),
                               jnum(jget(j, "phase_rad"), 0.0));
    if (strcmp(type, "ramp") == 0)
        return temporal_ramp(jnum(jget(j, "start_hz"), 0),
                             jnum(jget(j, "end_hz"), 200),
                             jnum(jget(j, "total_sec"), track_dur));
    if (strcmp(type, "steps") == 0) {
        jval_t *arr = jget(j, "steps");
        if (!arr || arr->type != J_ARR) return temporal_const(0);
        int n = arr->arr.cnt;
        step_t *steps = malloc(n * sizeof(step_t));
        for (int i = 0; i < n; i++) {
            jval_t *s = arr->arr.items[i];
            steps[i].hz           = jnum(jget(s, "hz"), 0);
            steps[i].duration_sec = jnum(jget(s, "duration_sec"), 1.0);
        }
        temporal_t *t = temporal_steps(steps, n);
        free(steps);
        return t;
    }
    fprintf(stderr, "Unknown temporal type: %s\n", type);
    return temporal_const(0);
}

static spatial_t *build_spatial(jval_t *j, int n_pages) {
    const char *type = jstr(jget(j, "type"));
    if (strcmp(type, "uniform") == 0)
        return spatial_uniform(n_pages);
    if (strcmp(type, "sequential") == 0)
        return spatial_sequential(n_pages);
    if (strcmp(type, "zipf") == 0)
        return spatial_zipf(n_pages, jnum(jget(j, "s"), 1.0));
    if (strcmp(type, "gaussian") == 0)
        return spatial_gaussian(n_pages,
                                jnum(jget(j, "center"), n_pages / 2.0),
                                jnum(jget(j, "sigma"), 1.0));
    if (strcmp(type, "all") == 0)
        return spatial_all(n_pages);
    if (strcmp(type, "hotspot") == 0) {
        jval_t *hp = jget(j, "hot_pages");
        int n_hot = hp && hp->type == J_ARR ? hp->arr.cnt : 0;
        int *hot  = malloc((n_hot ? n_hot : 1) * sizeof(int));
        for (int i = 0; i < n_hot; i++)
            hot[i] = (int)jnum(hp->arr.items[i], 0);
        double ratio = jnum(jget(j, "hot_ratio"), 0.8);
        spatial_t *s = spatial_hotspot(n_pages, hot, n_hot, ratio);
        free(hot);
        return s;
    }
    fprintf(stderr, "Unknown spatial type: %s\n", type);
    return spatial_uniform(n_pages);
}

/* ══════════════════════════════════════════════════════════════
   Public workload API
   ══════════════════════════════════════════════════════════════ */

workload_t *workload_load(const char *path) {
    jval_t *root = jload(path);
    if (!root) return NULL;

    workload_t *w = calloc(1, sizeof(*w));
    w->duration_sec = jnum(jget(root, "duration_sec"), 10.0);
    w->gt_log       = gt_log_create(10 * 1024 * 1024);

    /* allocate named regions */
    jval_t *regs = jget(root, "regions");
    if (regs && regs->type == J_ARR) {
        for (int i = 0; i < regs->arr.cnt && i < MAX_REGIONS; i++) {
            jval_t    *rj  = regs->arr.items[i];
            int n_pages    = (int)jnum(jget(rj, "pages"), 10);
            /* optional fixed VA: "address": "0x7f1000000000" or decimal string */
            uintptr_t addr = 0;
            jval_t *jaddr  = jget(rj, "address");
            if (jaddr && jaddr->type == J_STR && jaddr->s[0])
                addr = (uintptr_t)strtoull(jaddr->s, NULL, 0);
            else if (jaddr && jaddr->type == J_NUM)
                addr = (uintptr_t)(unsigned long long)jaddr->n;
            region_t *r = region_alloc(n_pages, addr);
            if (!r) { fprintf(stderr, "region_alloc failed for region %d\n", i); continue; }
            w->regions[w->n_regions++] = r;
        }
    } else {
        /* backwards compat: single region_pages at top level */
        int n_pages = (int)jnum(jget(root, "region_pages"), 10);
        w->regions[0] = region_alloc(n_pages, 0);
        if (!w->regions[0]) { free(w); jfree(root); return NULL; }
        w->n_regions  = 1;
    }

    /* build tracks */
    jval_t *tracks = jget(root, "tracks");
    if (tracks && tracks->type == J_ARR) {
        for (int i = 0; i < tracks->arr.cnt && i < MAX_TRACKS; i++) {
            jval_t *tj     = tracks->arr.items[i];
            int ridx       = (int)jnum(jget(tj, "region"), 0);
            if (ridx < 0 || ridx >= w->n_regions) {
                fprintf(stderr, "track %d: invalid region index %d\n", i, ridx);
                ridx = 0;
            }
            region_t   *r  = w->regions[ridx];
            double start   = jnum(jget(tj, "start_sec"), 0.0);
            double end     = jnum(jget(tj, "end_sec"),   w->duration_sec);
            temporal_t *tp = build_temporal(jget(tj, "temporal"), end - start);
            spatial_t  *sp = build_spatial(jget(tj, "spatial"), r->n_pages);
            w->tracks[w->n_tracks++] = track_create(r, ridx, sp, tp,
                                                    w->gt_log, start, end);
        }
    }

    jfree(root);
    return w;
}

void workload_run(workload_t *w, const char *gt_path) {
    struct timespec t0;
    clock_gettime(CLOCK_MONOTONIC, &t0);

    for (int i = 0; i < w->n_tracks; i++)
        track_start(w->tracks[i], &t0);

    /* sleep for duration */
    struct timespec dur = {
        .tv_sec  = (time_t)w->duration_sec,
        .tv_nsec = (long)((w->duration_sec - (long)w->duration_sec) * 1e9)
    };
    nanosleep(&dur, NULL);

    for (int i = 0; i < w->n_tracks; i++) track_stop(w->tracks[i]);
    for (int i = 0; i < w->n_tracks; i++) track_join(w->tracks[i]);

    /* write ground truth — header with region metadata first */
    FILE *f = fopen(gt_path, "w");
    if (f) {
        for (int i = 0; i < w->n_regions; i++)
            fprintf(f, "# region %d base=0x%lx pages=%zu\n",
                    i, (unsigned long)w->regions[i]->buf, w->regions[i]->n_pages);
        gt_log_flush(w->gt_log, f);
        fclose(f);
    } else perror(gt_path);

    long total = 0;
    for (int i = 0; i < w->n_tracks; i++) total += w->tracks[i]->access_count;
    printf("\nDone: %ld total accesses in %.1f s → ground truth: %s\n",
           total, w->duration_sec, gt_path);
}

void workload_free(workload_t *w) {
    if (!w) return;
    for (int i = 0; i < w->n_tracks; i++) {
        track_t *t = w->tracks[i];
        spatial_free(t->spatial);
        temporal_free(t->temporal);
        track_free(t);
    }
    gt_log_free(w->gt_log);
    for (int i = 0; i < w->n_regions; i++)
        region_free(w->regions[i]);
    free(w);
}
