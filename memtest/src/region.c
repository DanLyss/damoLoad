#include "region.h"
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/mman.h>

#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

region_t *region_alloc(size_t n_pages, uintptr_t address) {
    region_t *r = malloc(sizeof(*r));
    r->n_pages    = n_pages;
    r->size_bytes = n_pages * 4096;

    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
    void *hint = NULL;
    if (address) {
        flags |= MAP_FIXED_NOREPLACE;
        hint   = (void *)address;
    }
    r->buf = mmap(hint, r->size_bytes, PROT_READ | PROT_WRITE, flags, -1, 0);
    if (r->buf == MAP_FAILED) {
        fprintf(stderr, "mmap failed for region at 0x%lx (%zu pages)\n",
                (unsigned long)address, n_pages);
        free(r); return NULL;
    }
    for (size_t i = 0; i < r->size_bytes; i += 4096)
        *((volatile char *)r->buf + i) = 0;
    return r;
}

void region_free(region_t *r) {
    if (!r) return;
    munmap(r->buf, r->size_bytes);
    free(r);
}

