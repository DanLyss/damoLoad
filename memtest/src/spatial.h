#pragma once

typedef struct spatial spatial_t;

struct spatial {
    int  (*next)(spatial_t *self, double t_sec);
    void (*destroy)(spatial_t *self);
    void *params;
    int   n_pages;
};

spatial_t *spatial_uniform(int n_pages);
spatial_t *spatial_hotspot(int n_pages, int *hot_pages, int n_hot, double hot_ratio);
spatial_t *spatial_sequential(int n_pages);
spatial_t *spatial_zipf(int n_pages, double s);
spatial_t *spatial_gaussian(int n_pages, double center, double sigma);
spatial_t *spatial_all(int n_pages);  /* next() returns -1: touch ALL pages per tick */

void spatial_free(spatial_t *s);
