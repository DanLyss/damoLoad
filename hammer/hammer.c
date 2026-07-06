#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/mman.h>
#include <unistd.h>
#include <signal.h>
#include <stdint.h>

static volatile int running = 1;
static void on_sigint(int s) { (void)s; running = 0; }

int main(int argc, char **argv) {
  
    int target_hz  = argc > 1 ? atoi(argv[1]) : 2000;
    int nr_pages_arg = argc > 2 ? atoi(argv[2]) : 10;

    size_t region_size = 4096 * nr_pages_arg;
    void *buf = mmap(NULL, region_size, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (buf == MAP_FAILED) { perror("mmap"); return 1; }

    /* touch all pages to fault them in */
    for (size_t i = 0; i < region_size; i += 4096)
        *((volatile char *)buf + i) = 0;

    printf("PID:    %d\n",  getpid());
    printf("REGION: %p-%p\n", buf, (char *)buf + region_size);
    printf("TARGET: %d Hz\n", target_hz);
    fflush(stdout);

    signal(SIGINT, on_sigint);

    struct timespec interval = {
        .tv_sec  = 0,
        .tv_nsec = 1000000000L / target_hz,
    };

    long count = 0;
    time_t t0 = time(NULL);
    size_t nr_pages = (size_t)nr_pages_arg;

    while (running) {
        size_t page_off = (size_t)rand() % nr_pages * 4096;
        *((volatile char *)buf + page_off) = (char)(count & 0xFF);
        count++;
        clock_nanosleep(CLOCK_MONOTONIC, 0, &interval, NULL);

        if (count % target_hz == 0) {
            printf("[%lds] %ld accesses\n", time(NULL) - t0, count);
            fflush(stdout);
        }
    }

    printf("Total: %ld accesses in %lds\n", count, time(NULL) - t0);
    munmap(buf, region_size);
    return 0;
}
