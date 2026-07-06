# hammer — Minimal DAMON Load Generator

A single-file C program that hammers a memory region at a fixed rate and prints its PID and address range. Useful for quick manual DAMON experiments without setting up a full workload JSON.

---

## Build

```bash
gcc -O0 -o hammer hammer.c
```

## Usage

```
./hammer [hz] [pages]
```

| Argument | Default | Description                    |
|----------|---------|--------------------------------|
| `hz`     | 2000    | Target access rate (Hz)        |
| `pages`  | 10      | Region size in 4 KB pages      |

## Example

```bash
# Terminal 1 — start hammer
./hammer 500 20
# PID:    12345
# REGION: 0x7f1000000000-0x7f1000014000
# TARGET: 500 Hz

# Terminal 2 — record with DAMON (run as root)
damo record \
    --ops fvaddr \
    --target_pid 12345 \
    -r 0x7f1000000000-0x7f1000014000 \
    --monitoring_intervals 5ms 100ms 1s \
    --timeout 10 -o /tmp/hammer.data

# View heatmap
damo report heatmap --input /tmp/hammer.data
```

## What it does

1. `mmap`s `pages × 4096` bytes (anonymous, private)
2. Prefaults all pages with a write
3. Prints PID, region address range, and target Hz
4. Loops: picks a random page, writes one byte, sleeps `1/hz` seconds
5. Prints progress every `hz` accesses
6. Stops on `Ctrl-C`, prints total count

## Notes

- Uses `clock_nanosleep(CLOCK_MONOTONIC)` for timing — does not accumulate drift
- Access rate is approximate: sleep granularity is limited by the OS scheduler (~100µs)
- Actual DAMON-observable rate is capped at `1 / sample_interval = 200 Hz` (with default 5ms sampling)
- For structured workloads (sine, hotspot, multiple regions, ground truth logging) use `memtest` instead
