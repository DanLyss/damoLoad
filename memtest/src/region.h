#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    void   *buf;
    size_t  n_pages;
    size_t  size_bytes;
} region_t;

/* address=0 → let kernel choose; non-zero → MAP_FIXED_NOREPLACE at that VA */
region_t *region_alloc(size_t n_pages, uintptr_t address);
void      region_free(region_t *r);
