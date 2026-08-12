# DAMON kernel guide: `mm/damon/core.c` + `mm/damon/vaddr.c`

Source studied: `WSL2-Linux-Kernel` checkout, `mm/damon/` — Makefile reports
`VERSION=6 PATCHLEVEL=18 SUBLEVEL=35 EXTRAVERSION=.2`. `core.c` is 2958 lines,
`vaddr.c` is 1077 lines. This guide assumes zero prior DAMON knowledge and
ends at the level needed to safely modify the sampling policy or add a
region/page-type targeting option (see [Part 7](#part-7-answering-the-task-adjusting-sampling-and-targeting-region-types)
for that specific goal).

Companion header: `include/linux/damon.h` (963 lines) — every struct/enum
referenced below lives there unless stated otherwise. `mm/damon/ops-common.c`
holds helpers shared by `vaddr.c` and `paddr.c` (PTE/PMD accessed-bit
manipulation, folio filter matching).

## Contents

- [Part 1 — The 30-second mental model](#part-1-the-30-second-mental-model)
- [Part 2 — Vocabulary (the structs, bottom-up)](#part-2-vocabulary-the-structs-bottom-up)
  - [`struct damon_region`](#struct-damon_region-damonh76)
    - [Deep dive: `nr_accesses` vs `nr_accesses_bp`](#deep-dive-nr_accesses-vs-nr_accesses_bp-the-mechanical-difference)
  - [`struct damon_target`](#struct-damon_target-damonh100)
  - [`struct damos`](#struct-damos-damon-based-operation-scheme-damonh516)
    - [Deep dive: the 5 fields are a pipeline of gates](#deep-dive-the-5-fields-are-a-pipeline-of-gates-not-independent-settings)
  - [`struct damon_operations`](#struct-damon_operations-damonh615)
    - [Why this abstraction exists](#why-this-abstraction-exists)
    - [Deep dive: PMD vs PTE walk branches](#deep-dive-why-every-page-table-walk-has-two-branches-pmd-vs-pte)
  - [`struct damon_attrs`](#struct-damon_attrs-damonh706)
  - [`struct damon_ctx`](#struct-damon_ctx-damonh756)
- [Part 3 — How a target's region list comes to exist](#part-3-how-a-targets-region-list-comes-to-exist)
  - [The automatic path: vaddr's three-region heuristic](#the-automatic-path-vaddrs-three-region-heuristic)
  - [The external path: fixed addresses via sysfs](#the-external-path-fixed-addresses-via-sysfs)
- [Part 4 — Region lifecycle primitives (core.c)](#part-4-region-lifecycle-primitives-corec)
- [Part 5 — The kdamond main loop, statement by statement](#part-5-the-kdamond-main-loop-statement-by-statement)
  - [Deep dive: turning a quota's time/size/goals into one effective size](#deep-dive-turning-a-quotas-time-size-and-goal-limits-into-one-effective-size)
- [Part 6 — Talking to a running kdamond: damon_call and damos_walk](#part-6-talking-to-a-running-kdamond-damon_call-and-damos_walk)
- [Part 7 — Answering the task: adjusting sampling and targeting region types](#part-7-answering-the-task-adjusting-sampling-and-targeting-region-types)
  - [7.1 Adjust percentage of pages being sampled from each region](#71-adjust-percentage-of-pages-being-sampled-from-each-region)
  - [7.2 Target specific region types (anon, dma, etc.)](#72-target-specific-region-types-anon-dma-etc-yes-partially-implemented)
  - [7.3 Cheat-sheet: which function to touch for what](#73-cheat-sheet-which-function-to-touch-for-what)
- [Part 8 — File/function index](#part-8-filefunction-index-line-numbers-this-checkout)
- [Part 9 — Things worth re-verifying on the actual HongMeng-side kernel](#part-9-things-worth-re-verifying-on-the-actual-hongmeng-side-kernel)

---

## Part 1 — The 30-second mental model

DAMON = a kernel thread (**kdamond**) that, forever, in a loop:

1. picks one random byte inside each monitored region,
2. sleeps `sample_interval` µs,
3. checks whether that byte's page was accessed (CPU's PTE **Accessed**
   bit) during the sleep,
4. repeats step 1–3 `aggr_interval / sample_interval` times, accumulating an
   access count per region,
5. every `aggr_interval`, snapshots the counts as `region->nr_accesses`,
   then adaptively **merges** similar-frequency neighboring regions and
   **splits** regions that might be hiding sub-patterns,
6. optionally applies **DAMOS schemes** (policy: "if a region's access
   pattern matches X, do Y" — e.g. madvise(COLD), reclaim, migrate) to
   regions whose `(size, nr_accesses, age)` fits a user-defined pattern.

`core.c` implements everything in this list *except* "how do I read the
Accessed bit for this specific kind of address space" — that's delegated to
a pluggable **`struct damon_operations`** vtable. `vaddr.c` is one
implementation of that vtable, for monitoring a **process's virtual address
space** (anonymous mmaps, file mappings, heap, stack — literally what
`damoLoad`'s `memtest` exercises via `fvaddr`).

```
                     ┌─────────────────────────────┐
 userspace (damo) ──▶│   sysfs (mm/damon/sysfs.c)  │  (not covered here)
                     └──────────────┬──────────────┘
                                    │ struct damon_ctx
                                    ▼
                     ┌─────────────────────────────┐
                     │   core.c: kdamond_fn()       │  <- the engine
                     │   (sampling, aggregation,    │
                     │    merge/split, DAMOS apply) │
                     └──────────────┬──────────────┘
                                    │ ctx->ops.*  (vtable calls)
                                    ▼
                     ┌─────────────────────────────┐
                     │   vaddr.c (DAMON_OPS_VADDR/  │  <- "how" for VA space
                     │   DAMON_OPS_FVADDR)          │
                     │   paddr.c (DAMON_OPS_PADDR)  │  <- sibling, not covered
                     └─────────────────────────────┘
```

---

## Part 2 — Vocabulary (the structs, bottom-up)

Read `include/linux/damon.h` structs in this order — each builds on the
previous.

### `struct damon_region` (damon.h:76)
The atomic unit of monitoring: one `[start, end)` virtual-address interval
plus its measured stats.

```c
struct damon_region {
    struct damon_addr_range ar;       // [start, end)
    unsigned long sampling_addr;      // the one address sampled this interval
    unsigned int nr_accesses;         // # of sample intervals w/ access, this aggr window
    unsigned int nr_accesses_bp;      // same thing, basis-points, updated every sample (moving sum)
    struct list_head list;            // sibling regions of the same target
    unsigned int age;                 // # aggr intervals the access pattern held steady
    unsigned int last_nr_accesses;    // private: previous aggr window's nr_accesses
};
```

Key subtlety: `nr_accesses` is only authoritative *after* an aggregation
interval finishes (`kdamond_reset_aggregated()` copies it into
`last_nr_accesses` and zeroes it). `nr_accesses_bp` is a live "basis points"
(1/10000) moving-sum approximation of the same value, useful mid-window
(e.g. for DAMOS pattern-matching that must run every sample, not just every
aggregation).

#### Deep dive: `nr_accesses` vs `nr_accesses_bp` — the mechanical difference

Both fields are touched from the same call,
`damon_update_region_access_rate(r, accessed, attrs)` (core.c:2915),
invoked once per region on *every* sample interval regardless of hit or
miss:

```c
r->nr_accesses_bp = damon_moving_sum(r->nr_accesses_bp,
        r->last_nr_accesses * 10000, len_window,
        accessed ? 10000 : 0);      // (A) runs unconditionally, every tick
if (accessed)
    r->nr_accesses++;               // (B) only runs on a hit
```

`damon_moving_sum(mvsum, nomvsum, len_window, new_value)` (core.c:2898)
is just `mvsum - nomvsum/len_window + new_value` — a lightweight
pseudo-moving-sum that doesn't literally remember the last `len_window`
samples, it assumes the dropped-off old sample was
`last_nr_accesses*10000/len_window` (a uniform estimate) and swaps it
for the new one.

The difference that matters: **(A) executes on every tick, hit or
miss — a miss actively pulls `nr_accesses_bp` down.** **(B) is a
conditional — on a miss, that line is simply skipped, so `nr_accesses`
stays byte-for-byte unchanged**, it isn't "updated to reflect the
miss" in any sense, it's just not written to.

Concrete trace, `len_window = 4` samples/aggr-window,
`last_nr_accesses = 2` (⇒ `nr_accesses_bp` starts at `20000`):

| tick | accessed | `nr_accesses_bp` (A, always recomputed) | `nr_accesses` (B, hit-only) |
|---|---|---|---|
| start | — | 20000 | 0 |
| 1 | true  | 20000 − 20000/4 + 10000 = **25000** | 0+1 = **1** |
| 2 | **false** | 25000 − 20000/4 + 0 = **20000** | **unchanged: 1** |
| 3 | true  | 20000 − 20000/4 + 10000 = **25000** | 1+1 = **2** |
| 4 | true  | 25000 − 20000/4 + 10000 = **30000** | 2+1 = **3** |

At tick 2, `nr_accesses_bp` visibly moves (25000→20000) while
`nr_accesses` doesn't move at all — that's the entire distinction. At
window end, `kdamond_reset_aggregated()` asserts
`nr_accesses_bp == nr_accesses * 10000` (`30000 == 3*10000` ✓,
`damon_warn_fix_nr_accesses_corruption`, core.c:1550) — the two are
only guaranteed to agree exactly at that boundary, which is precisely
why DAMOS pattern matching (`__damos_valid_target`, core.c:1644) reads
`r->nr_accesses_bp / 10000` instead of `r->nr_accesses` when it needs a
number mid-window.

### `struct damon_target` (damon.h:100)
One monitored entity — for `vaddr`/`fvaddr` this is one process, identified
by `pid` (a `struct pid *`, reference-counted). Owns a linked list of
`damon_region`s (`regions_list`, count cached in `nr_regions`). A context
can have multiple targets (multiple processes monitored together).

### `struct damos` (DAMON-based Operation Scheme, damon.h:516)
The **policy** object: "regions matching `pattern` get `action` applied, at
most every `apply_interval_us`, bounded by `quota`, gated by `wmarks`,
narrowed by `filters`". This is the piece that answers "what happens to a
region", as opposed to `damon_attrs` which answers "how is a region
measured". Fields worth knowing:

- `pattern` (`struct damos_access_pattern`): `[min_sz_region,max_sz_region]
  × [min_nr_accesses,max_nr_accesses] × [min_age_region,max_age_region]`
  — a 3D box a region's `(size, nr_accesses, age)` must fall inside.
- `action` (`enum damos_action`, damon.h:129): `DAMOS_WILLNEED`, `_COLD`,
  `_PAGEOUT`, `_HUGEPAGE`, `_NOHUGEPAGE`, `_LRU_PRIO`, `_LRU_DEPRIO`,
  `_MIGRATE_HOT`, `_MIGRATE_COLD`, `_STAT` (no-op, just count).
- `quota` (`struct damos_quota`, damon.h:234): caps the action's cost per
  `reset_interval`, either directly (`ms`, `sz`) or via an auto-tuned
  feedback loop against `goals` (e.g. keep some-memory PSI at a target).
- `wmarks` (`struct damos_watermarks`, damon.h:293): activates/deactivates
  the whole scheme based on a system metric (currently only
  `DAMOS_WMARK_FREE_MEM_RATE`).
- `filters` / `ops_filters` (`struct damos_filter`, damon.h:394): **the
  existing region/page-type targeting mechanism** — see
  [Part 7](#part-7-answering-the-task-adjusting-sampling-and-targeting-region-types).

#### Deep dive: the 5 fields are a pipeline of gates, not independent settings

Reading the struct alone makes `pattern`/`quota`/`wmarks`/`filters` look
like a flat list of settings. What they actually are is **6 sequential
checks**, each only reached if the previous passed, spread across
`kdamond_apply_schemes` (core.c:2249) → `damon_do_apply_schemes`
(core.c:1963) → `damos_apply_scheme` (core.c:1895), evaluated for every
`(scheme, region)` pair on every sample interval:

```
1. TIME?     passed_sample_intervals >= s->next_apply_sis ?      (apply_interval_us)
2. ACTIVE?   s->wmarks.activated == true ?                        (wmarks)
3. BUDGET?   quota->charged_sz < quota->esz ?                     (quota)
4. MATCH?    __damos_valid_target(r, s) — (size,nr_accesses,age) in pattern's 3D box
             (+ get_scheme_score(r) >= quota->min_score, if quota has goals)
5. FILTER(core)  damos_filter_out() — ADDR/TARGET filters, may split the region
6. FILTER(ops)   inside ctx->ops.apply_scheme(), per-page — ANON/ACTIVE/... (vaddr.c: Part 7.2)
                 → only now does the actual madvise()/migrate/reclaim happen
```

`action` isn't a gate at all — it's what happens at the very end, once
every gate above passed.

**Worked example** — a reclaim-style scheme, *"page out fully-cold
anonymous regions that have stayed cold for 3+ aggregation windows, but
only when free memory is getting low, capped at 100ms of work per
second"*:

```c
pattern:  min_sz_region=0, max_sz_region=ULONG_MAX,
          min_nr_accesses=0, max_nr_accesses=0,      // zero hits this window
          min_age_region=3,  max_age_region=UINT_MAX  // cold for 3+ windows straight
action:   DAMOS_PAGEOUT
apply_interval_us: 0                                  // => defaults to aggr_interval
quota:    { ms = 100, reset_interval = 1000 }          // <=100ms of work per second
wmarks:   { metric = DAMOS_WMARK_FREE_MEM_RATE, high = 500, mid = 400, low = 50 }
filters:  [ { type = DAMOS_FILTER_TYPE_ANON, matching = true, allow = true } ]
```

For a region with `nr_accesses_bp/10000 == 0`, `age == 5`, `sz == 8KB`:
gate 1 fires at the aggregation boundary; gate 2 depends on the current
`free_mem_rate` (see the hysteresis note below); gate 3 depends on how
much of the 100ms/s budget is already spent this `reset_interval`; gate
4 matches (`0` in `[0,0]`, `5 >= 3`, size in range); gate 5 has nothing
to check (no `ADDR`/`TARGET` filters set); gate 6 is where the concrete
`filters: [ANON]` entry would apply — **except**, per Part 7.2, vaddr's
`damos_va_filter_out()` only actually gets exercised for `DAMOS_STAT`
and `MIGRATE_*` actions in this file; for a plain `madvise()`-backed
action like `DAMOS_PAGEOUT`, `vaddr.c` never calls the per-page filter
path at all, so this `ANON` entry would silently have no effect — a
direct, concrete consequence of the "vaddr/fvaddr don't support
ANON/MEMCG filters" note already in Part 7.2, now traced through to
where it actually bites.

**`wmarks` hysteresis** (`damos_wmark_wait_us`, core.c:2505) — the
struct doc's one-liner ("active between low and high") hides that the
three thresholds `high > mid > low` form 3 bands with *memory*, not 2:

```c
if (metric > high || metric < low) {              // either extreme
    activated = false; return interval;             // -> OFF, stays checked every `interval`
}
if (mid <= metric && metric <= high && !activated)  // "grey zone", currently OFF
    return interval;                                 // -> stays OFF (won't turn on here)
activated = true; return 0;                          // otherwise -> ON (or stays ON)
```

So: `metric` outside `[low, high]` → always OFF. `metric` in
`[mid, high]` → turns ON only if it *was already* ON (i.e. it doesn't
spontaneously activate here). `metric` in `[low, mid)` → turns ON
unconditionally. Net effect: to go from OFF to ON, the metric has to
actually cross below `mid`, not just below `high` — cheap protection
against flapping right at the `high` boundary.

### `struct damon_operations` (damon.h:615)

#### Why this abstraction exists

Everything in `core.c` (timers, adaptive merge/split, the whole DAMOS
pipeline from the previous section) is generic — it doesn't care *what*
memory it's watching. But two specific steps — "check whether this
memory was accessed" and "apply this action to this memory" — have
completely different mechanics depending on the address space: for a
process's virtual memory (`vaddr`/`fvaddr`) you need that process's
`mm_struct`, `mmap_read_lock`, a page-table walk, and the PTE/PMD
Accessed bit; for physical memory (`paddr`, not covered in this guide)
there's no single `mm_struct` to anchor on — a physical page can be
mapped into several processes or none, so the same check has to go
through reverse-mapping instead of a direct address-space walk.

Rather than littering `core.c` with `if (ops_id == VADDR) ... else if
(ops_id == PADDR) ...`, DAMON defines an abstract 9-function contract
(this struct) and a registry (`damon_register_ops`/`damon_select_ops`,
core.c:73/100, keyed by `enum damon_ops_id`) — the same "ops struct as
vtable" pattern the kernel uses everywhere (`file_operations`,
`block_device_operations`, ...) to separate a generic engine from a
swappable backend. The payoff is concretely visible in how cheap
`fvaddr` was to add: not a new implementation of "how to check access",
just `vaddr`'s vtable copied with two fields zeroed
(`damon_va_initcall`, vaddr.c:1046-1073). It also means `core.c`
deliberately knows nothing about VMAs, `mm_struct`, or page types
(anon/file/...) — that knowledge is intentionally quarantined inside
the backend (`vaddr.c`). Direct consequence for the task from Part 7:
any "target monitoring by region type" feature that needs `vma`/page
information has to live in `vaddr.c`, not `core.c`, precisely because
of this boundary.

The vtable `vaddr.c` fills in. Every callback receives `struct damon_ctx
*context` and pulls target/region lists out of it:

| callback | called when | vaddr.c's implementation |
|---|---|---|
| `init` | once, before monitoring starts | `damon_va_init` — builds initial regions from `/proc/pid/maps`-equivalent VMA walk |
| `update` | every `ops_update_interval` | `damon_va_update` — re-derives 3 regions from current VMAs (mmap/munmap since last check) |
| `prepare_access_checks` | every `sample_interval`, before sleeping | `damon_va_prepare_access_checks` — picks a random `sampling_addr` per region, clears its Accessed bit |
| `check_accesses` | every `sample_interval`, after sleeping | `damon_va_check_accesses` — re-reads the Accessed bit, updates `nr_accesses[_bp]` |
| `get_scheme_score` | during DAMOS quota-based prioritization | `damon_va_scheme_score` — hot/cold heuristic score in `[0,99]` |
| `apply_scheme` | when a region matches a scheme's pattern | `damon_va_apply_scheme` — dispatches to `madvise()`, migration, or stat-only |
| `target_valid` | every loop iteration (stop condition check) | `damon_va_target_valid` — true iff the pid's task still exists |
| `cleanup_target` / `cleanup` | target/context teardown | drop the `pid` reference |

#### Deep dive: why every page-table walk has two branches (PMD vs PTE)

`sampling_addr` is a byte address, but the CPU's Accessed bit lives on
a *page table entry*, and a mapping can be backed either by a normal
4KB page (leaf at the **PTE** level) or, if Transparent Huge Pages are
in play, by one 2MB page (leaf directly at the **PMD** level — there's
no PTE table underneath at all in that case). A page-table walker can't
know in advance which one it'll hit for a given address, so every
walk callback in this file that touches leaf entries
(`damon_mkold_pmd_entry` vaddr.c:306, `damon_young_pmd_entry` vaddr.c:439,
`damos_va_migrate_pmd_entry`/`_pte_entry` vaddr.c:722/762,
`damos_va_stat_pmd_entry` vaddr.c:900) starts by checking
`pmd_trans_huge(pmdp_get(pmd))` under `pmd_lock()`: if true, handle the
whole 2MB region right there (folio size becomes `HPAGE_PMD_SIZE`) and
return; if false, fall through to `pte_offset_map_lock()` and handle it
as an ordinary one-page PTE. This is plain page-table topology, not
DAMON-specific policy — but it's *why* these functions look twice as
long as "read one Accessed bit" would suggest, and it's why hugetlbfs
(a third, separate leaf level) gets its own dedicated
`*_hugetlb_entry` callback (`CONFIG_HUGETLB_PAGE`-gated) registered in
the same `mm_walk_ops` struct instead of being folded into the PMD
branch — hugetlb pages aren't part of the regular page-table hierarchy
`pagewalk.c` descends by default.

Two `damon_operations` instances are registered from `vaddr.c`'s
`damon_va_initcall()` (vaddr.c:1046): `DAMON_OPS_VADDR` (auto-discovers
regions from the whole address space) and `DAMON_OPS_FVADDR` (same
callbacks, but `init`/`update` are `NULL` — **the caller must set the
regions manually via sysfs**, and they're never auto-adjusted to follow
new mmaps). **This is the mode `damoLoad`/`run_memtest.sh` uses**, precisely
because it needs DAMON to watch exact, externally-known address ranges.

### `struct damon_attrs` (damon.h:706)
The **measurement knobs**, orthogonal to `damos` (policy):

- `sample_interval`, `aggr_interval`, `ops_update_interval` — the three
  timers described in Part 1.
- `min_nr_regions` / `max_nr_regions` — bounds the adaptive region count
  (see Part 5's merge/split discussion). **This is what
  `nr_regions_sweep_report.py` in this repo sweeps.**
- `intervals_goal` — optional auto-tuner that adjusts `sample_interval`
  itself to hit a target "observed access events ratio" (`kdamond_tune_intervals()`,
  core.c:1619). Off by default (`aggrs == 0`).

### `struct damon_ctx` (damon.h:756)
The root object: one `damon_attrs`, one `damon_operations`, a list of
`damon_target`s, a list of `damos` schemes, plus the kdamond thread handle
and bookkeeping (`passed_sample_intervals`, the "when to fire next" `_sis`
counters, IPC channels described in Part 6). One `damon_ctx` == one
`kdamond` kernel thread == one `damo record`/kdamond sysfs directory.

---

## Part 3 — How a target's region list comes to exist

Two different mechanisms populate `t->regions_list` for the first time,
depending on which `damon_operations` the target uses (Part 2 above) —
`vaddr`'s automatic VMA-based heuristic, or `fvaddr`'s fully external,
sysfs-driven path. Both are worth walking through in detail, since this is
the very first thing that happens for a target and it explains facts
(exactly-3-regions-per-vaddr-target, the "sorted regions" requirement for
fvaddr) that are otherwise easy to misread as arbitrary.

### The automatic path: vaddr's three-region heuristic

Referenced from the `damon_operations` table in Part 2 above (`init`/`update`
rows) — worth walking through properly since it's the first thing that runs
and it explains why a freshly-started `vaddr` context always has **exactly 3
regions per target**, not one-per-VMA.

The problem: a process's real memory map is dozens of small VMAs (heap,
several mmaps, libraries, stack) separated by unmapped gaps. Monitoring
every VMA as its own region is wasteful (most gaps are permanently
unaccessed — no point spending sampling budget there), but collapsing
the *entire* `[lowest_addr, highest_addr)` span into one region is worse:
it would include the one or two **huge** unmapped gaps that are a normal
part of every process's layout — the heap↔mmap gap and the
mmap↔stack gap — and DAMON's adaptive split/merge machinery would waste
cycles rediscovering that those multi-GB gaps are "cold" over and over.

`vaddr.c`'s own comment (vaddr.c:225-238) gives the picture directly:

```
  <heap>
  <BIG UNMAPPED REGION 1>
  <uppermost mmap()-ed region>
  (other mmap()-ed regions and small unmapped regions)
  <lowermost mmap()-ed region>
  <BIG UNMAPPED REGION 2>
  <stack>
```

So `__damon_va_three_regions()` (vaddr.c:120) walks the VMA list once
(`for_each_vma`, under `mmap_read_lock` — see `damon_va_three_regions()`,
vaddr.c:179, which takes the lock and puts the `mm`), and while walking
tracks the **two single biggest gaps** between consecutive VMAs
(`first_gap` = biggest, `second_gap` = second biggest — a simple running
top-2, no sorting of all gaps needed). Whatever gaps exist elsewhere
(small holes between library mmaps, etc.) are *not* excluded — only these
two are assumed to correspond to the heap-mmap and mmap-stack gaps.

That yields exactly 3 address ranges:
`[first_vma.start, first_gap.start)`,
`[first_gap.end, second_gap.end_boundary)`,
`[second_gap.end, last_vma.end)` (see the `regions[]` assignment,
vaddr.c:164-169 — note the two gaps get address-sorted first, since the
"biggest" and "second biggest" aren't necessarily in address order).

`__damon_va_init_regions()` (vaddr.c:239) then takes those 3 ranges and,
for each, further **evenly splits** it into `nr_pieces = range_size / sz`
sub-regions (`damon_va_evenly_split_region`, vaddr.c:65), where `sz` is
the total mapped span divided by `min_nr_regions` (vaddr.c:260-263) — i.e.
`min_nr_regions` isn't just a merge-time floor, it also sets the *initial*
region granularity before any access data exists to adapt on.

`damon_va_update()` (vaddr.c:294) re-runs the same 3-region computation on
every `ops_update_interval` and feeds the result through
`damon_set_regions()` (core.c:211, Part 4 below) — which is the generic
"reconcile my region list to match this new set of ranges" routine, so
newly appeared VMAs get picked up (or, if a big-enough gap moved, the
region boundaries shift) without discarding existing regions' accumulated
`nr_accesses`/`age` where their address range still exists.

**Only for `DAMON_OPS_VADDR`.** Recall from the ops-registration table
(Part 2) that `DAMON_OPS_FVADDR` sets `init`/`update` to `NULL` — this
entire heuristic is skipped for `fvaddr`. That's exactly why
`run_memtest.sh` (this repo) has to construct DAMON's region list itself
from memtest's printed mmap addresses and push it in via sysfs: nothing
in the kernel will do the "find the 3 real regions" work for fixed-address
monitoring, by design (fixed mode assumes the caller already knows the
exact ranges it cares about).

### The external path: fixed addresses via sysfs

`ops.init`/`ops.update == NULL` just means "nothing calls
`damon_set_regions()` automatically for you" — it doesn't mean the
fixed-address path bypasses that function. `mm/damon/sysfs.c` (outside
this guide's core.c/vaddr.c scope, but the only place that actually
answers "what happens with fixed addresses") does the job directly:

- Userspace writes `targets/<i>/regions/nr_regions = N`, then
  `regions/<j>/start`/`end` for each region, into the target's sysfs
  tree (this is what `damo`/`run_memtest.sh` do).
- On `echo on` (start) or `echo commit` (update a *running* kdamond),
  `damon_sysfs_set_regions()` (sysfs.c:1338) validates the array — each
  `start <= end`, **and** `ranges[i-1].end <= ranges[i].start` for every
  consecutive pair, i.e. strictly non-overlapping, ascending order, or
  it fails with `-EINVAL`. This is the exact source of the "DAMON
  kernel sysfs interface rejects unsorted regions" behavior this repo's
  own top-level README already documents and works around by sorting
  before writing.
- It then calls **the same generic `damon_set_regions()`** (core.c:211,
  Part 4) that `damon_va_update()` uses internally for `vaddr` — there
  is no separate "how to set fvaddr regions" function anywhere. This
  *one specific step* — deciding the region boundaries — never touches
  `vaddr.c`. Everything else about `fvaddr` monitoring (sampling,
  DAMOS) still runs through the exact same `vaddr.c` callbacks as
  `vaddr` — see the callback table in Part 2, where only `init`/`update`
  are nulled out, not the other seven.
- For `commit` specifically (updating a region set on an *already
  running* kdamond, without stop/restart): `damon_sysfs_commit_input()`
  (sysfs.c:1463) rebuilds a whole throwaway `damon_ctx` from the current
  sysfs tree and merges it into the live one via `damon_commit_ctx()`
  (core.c:1235, Part 6) — itself dispatched through `damon_call()`
  (Part 6's IPC mechanism), so it's race-safe against the kdamond
  thread's own loop instead of poking `regions_list` from outside.

Net picture: for `fvaddr`, region *placement* is 100% external
(sysfs/userspace decides the addresses), but region *bookkeeping*
(allocating `damon_region`s, splicing them into the sorted list, fixing
up overlaps) is the identical core.c machinery vaddr uses — the only
thing fvaddr skips is the *automatic, periodic* re-derivation from VMAs.
What it does **not** skip is DAMON's adaptive merge/split machinery
(Part 5) — that's pure `core.c` logic, unconditional, identical for
`vaddr` and `fvaddr` alike, so a target's *internal* region boundaries
keep changing every aggregation window regardless of how the *outer*
address range set was established.

---

## Part 4 — Region lifecycle primitives (core.c)

These are the low-level list operations everything else is built from
(`core.c:121`–`267`):

- `damon_new_region(start, end)` — allocate from `damon_region_cache`
  (a `kmem_cache`, initialized once in `damon_init()`, core.c:2944).
- `damon_add_region` / `damon_insert_region` (inline, damon.h:880) —
  append or insert into `t->regions_list` (a plain doubly-linked list,
  **kept sorted by address** by convention — nothing enforces this except
  callers being careful, which is exactly why `run_memtest.sh` sorts
  regions before configuring DAMON via sysfs, per this repo's own README).
- `damon_destroy_region` = `damon_del_region` + `damon_free_region`.
- `damon_split_region_at(t, r, sz_r)` (core.c:2379) — split `r` into
  `[start, start+sz_r)` and `[start+sz_r, end)`, the second inheriting
  `r`'s current stats (age, nr_accesses). Used by DAMOS quota charging,
  filter address-range matching, and adaptive splitting.
- `damon_set_regions(t, ranges[], nr_ranges, min_sz_region)` (core.c:211)
  — the general "make `t`'s regions match this new set of address ranges"
  routine: destroys regions with no overlap in the new ranges, resizes/
  fills-holes for regions that do overlap. Used by `vaddr.c`'s
  `damon_va_update()` (VMA changed) and by sysfs commit paths.

---

## Part 5 — The kdamond main loop, statement by statement

Everything converges in **`kdamond_fn()`** (core.c:2647), the kernel thread
body. Read it side-by-side with this table:

```c
while (!kdamond_need_stop(ctx)) {
    if (kdamond_wait_activation(ctx)) break;        // (a)
    if (ops.prepare_access_checks) ops.prepare_access_checks(ctx);  // (b)
    kdamond_usleep(sample_interval);                 // (c)
    ctx->passed_sample_intervals++;
    if (ops.check_accesses) max_nr_accesses = ops.check_accesses(ctx); // (d)
    if (passed >= next_aggregation_sis)
        kdamond_merge_regions(ctx, max_nr_accesses/10, sz_limit);      // (e)
    kdamond_call(ctx, false);                        // (f)
    if (!list_empty(&ctx->schemes)) kdamond_apply_schemes(ctx);        // (g)
    if (passed >= next_aggregation_sis) {
        maybe kdamond_tune_intervals(ctx);            // (h)
        kdamond_reset_aggregated(ctx);                // (i)
        kdamond_split_regions(ctx);                   // (j)
    }
    if (passed >= next_ops_update_sis)
        if (ops.update) ops.update(ctx);              // (k)
}
```

**(a) `kdamond_wait_activation`** (core.c:2594) — blocks (sleeping,
polling watermarks) until at least one scheme's watermark says "go", or
there are no schemes (then returns immediately). Also drains pending
`damon_call()` requests while waiting, so external callers aren't starved
if all schemes are inactive.

**(b)+(c)+(d) — one sampling round.** This triad is *the* sampling policy:
`prepare_access_checks` marks "old" (clears Accessed bit for) each region's
one `sampling_addr`; the thread sleeps exactly `sample_interval`; then
`check_accesses` re-reads the bit. **Only one address per region is ever
sampled per interval** — this is the single biggest fact governing
"percentage of pages sampled", see Part 7.

**(e) `kdamond_merge_regions`** (core.c:2353) — merges adjacent regions
whose `nr_accesses` differ by ≤ `threshold` (starts at `max_nr_accesses/10`,
i.e. dynamic 10%-of-max noise tolerance; doubles and retries if the region
count is still above `max_nr_regions`) and whose combined size doesn't
exceed `sz_limit = damon_region_sz_limit(ctx)` (≈ total monitored bytes /
`min_nr_regions`, core.c:1284). This runs **every aggregation**, not every
sample — despite being placed before the aggregation-only block below, it
guards internally on `passed_sample_intervals >= next_aggregation_sis`.

**(f) `kdamond_call`** (core.c:2551) — the mechanism for `damon_call()`
(Part 6): drains queued `damon_call_control` requests and invokes their
`fn` synchronously, *inside* the kdamond thread, right after a sampling
round finishes. This is why `damon_call()` callbacks can touch
`ctx`/targets/regions without extra locking — they run on the same thread
that owns them.

**(g) `kdamond_apply_schemes`** (core.c:2249) — for every scheme whose
`next_apply_sis` has arrived and whose watermark is active: recompute its
effective quota (`damos_adjust_quota`, which also builds a
size-per-score histogram for quota-based prioritization), then for every
region of every target call `damon_do_apply_schemes()` (core.c:1963),
which per-scheme checks quota remaining → charged-region skip → pattern
match (`damos_valid_target`) → calls `damos_apply_scheme()` → which itself
does the quota-boundary split, the **filter check
(`damos_filter_out`)**, and finally `ctx->ops.apply_scheme()`.

#### Deep dive: turning a quota's time/size/goals into one effective size

`struct damos_quota` gives the user three independent, optional ways to
bound a scheme (time budget `ms`, byte budget `sz`, or PSI/memory-ratio
`goals`), but the enforcement code (`damos_skip_charged_region`,
`damos_apply_scheme`) only ever checks *one* number: `quota->esz`
("effective size"). `damos_set_effective_quota()` (core.c:2138) is where
the three collapse into it, once per `reset_interval`
(`damos_adjust_quota`, core.c:2188, decides when a new charge window has
started via `time_in_range_open` against `quota->charged_from`):

1. If `ms` is set: convert time → bytes using **measured throughput**
   from the *previous* window (`total_charged_sz / total_charged_ns`,
   or a 1024-page/s guess if there's no history yet) — `esz = min(throughput * ms, esz)`.
2. If `goals` is non-empty: run `damos_quota_score()` (core.c:2120),
   which — for each goal — measures the metric (`DAMOS_QUOTA_SOME_MEM_PSI_US`
   reads global PSI deltas, `DAMOS_QUOTA_NODE_MEM_USED_BP`/`_FREE_BP` read
   `si_meminfo_node()`, `DAMOS_QUOTA_USER_INPUT` trusts a caller-set value)
   and takes the *highest* `current_value/target_value` ratio across goals
   (highest score ⇒ most conservative ⇒ least aggressive action, by design).
   That score in basis points feeds `damon_feed_loop_next_input()`
   (core.c:2012) — a simple proportional controller: if last window
   *overshot* the goal (score > 10000bp target), shrink next `esz`
   proportionally to the overshoot; if it *undershot*, grow it — clamped
   so it never hits exactly zero. This is the same generic feed-loop
   function `kdamond_tune_intervals` (below) reuses for interval
   auto-tuning — one small piece of control-theory code backs both
   features.
3. `sz` (a hard byte cap), if set, always wins as a final `min()`.

Net effect: **`esz` bytes is the only thing `damos_apply_scheme` actually
enforces**, everything else is just different ways to compute that one
number every `reset_interval`.

**(h) `kdamond_tune_intervals`** (core.c:1619) — only if
`attrs.intervals_goal.aggrs` is set; feedback-loop-adjusts
`sample_interval`/`aggr_interval` toward a target "observed access ratio".

**(i) `kdamond_reset_aggregated`** (core.c:1562) — for every region:
trace it, copy `nr_accesses` → `last_nr_accesses`, zero `nr_accesses`.
This is the point at which "this aggregation window's answer" becomes
final and the next window starts from zero.

**(j) `kdamond_split_regions`** (core.c:2437) — if the current region
count is ≤ `max_nr_regions/2`, randomly splits every region into 2 (or 3,
if the count has been stagnant and is < `max_nr_regions/3`) unevenly-sized
(10%–90%) pieces (`damon_split_regions_of` → `damon_rand`). Purpose: hedge
against a region secretly containing two different sub-patterns that a
single `nr_accesses` value can't reveal; if the split was pointless, the
*next* merge pass folds them back together. This split/merge tug-of-war is
DAMON's whole "adaptive regions" idea — it's how a fixed sampling budget
(bounded by `max_nr_regions`) tracks a changing access pattern without the
user hand-tuning region boundaries.

**(k) `ops.update`** — for `vaddr`, re-syncs regions to current VMAs
(new/removed mmaps). **`fvaddr` sets this callback to `NULL`** — fixed
regions never auto-adjust, by design (see Part 2's table).

---

## Part 6 — Talking to a running kdamond: damon_call and damos_walk

Two thread-safe ways external code (sysfs write handlers, kernel modules
using DAMON directly) affects/inspects a *running* kdamond, without races:

- **`damon_call(ctx, control)`** (core.c:1479) — enqueue `control->fn` to
  run on the kdamond thread itself, at point (f) above. If
  `control->repeat` is false, blocks the caller until done and returns the
  function's result. This is how `damon_set_attrs()`,
  `damon_commit_ctx()`, and friends are safely applied to a live context —
  **any programmatic policy change (e.g. writing a new sampling
  percentage) must go through this**, not direct struct mutation, or it
  races with the kdamond thread.
- **`damos_walk(ctx, control)`** (core.c:1522) — enqueue a callback that
  fires once per region right after DAMOS applied (or attempted) an action
  to it, for one `apply_interval_us` cycle of each scheme. Used for
  observability (e.g. `damo report` DAMOS-target dumps), not policy.

---

## Part 7 — Answering the task: adjusting sampling and targeting region types

### 7.1 "Adjust percentage of pages being sampled from each region"

There is **no direct "sample N% of a region's pages" knob** — the sampling
unit is fixed at exactly **one address per region per `sample_interval`**
(`__damon_va_prepare_access_check`, vaddr.c:409: `r->sampling_addr =
damon_rand(r->ar.start, r->ar.end)`). "Coverage density" is instead an
*emergent* property of three independent levers, all in `core.c` /
`damon_attrs`:

1. **Region granularity** — smaller regions ⇒ each region's one sample
   represents fewer pages ⇒ effectively higher "percent of address space
   actively probed" per unit time, at the cost of more regions to sample
   each interval. Bounded by `min_nr_regions`/`max_nr_regions`
   (`damon_region_sz_limit`, core.c:1284, and the merge/split dance in
   Part 5 (e)/(j)) — **this is the knob `nr_regions_sweep_report.py`
   already sweeps in this repo**.
2. **Sampling rate over time** — `sample_interval` controls how often the
   one-address-per-region probe fires; more probes per `aggr_interval`
   raises statistical confidence per region without touching region count.
3. **Multiple samples per region per interval** — not implemented
   anywhere in `core.c`/`vaddr.c` today. To make a literal "sample X% of
   a region's pages per interval" feature, the natural insertion points
   are:
   - `struct damon_region`: currently holds one `sampling_addr`; you'd
     need either an array of them or a count-based sub-sampling scheme.
   - `__damon_va_prepare_access_check()` (vaddr.c:409) and
     `__damon_va_check_access()` (vaddr.c:560): currently pick/check
     exactly one address; would need to loop over K addresses
     (K = `region_size * pct / PAGE_SIZE`) and aggregate their
     young-bit results before calling
     `damon_update_region_access_rate()` (core.c:2915, which itself is
     already written generically — it just wants a single `accessed`
     bool per call, so it can be called K times per interval to
     accumulate, or you extend it to take a fraction).
   - Cost model: each extra sampled address per region is another
     `walk_page_range()` (page-table walk under `mmap_read_lock`), so a
     literal "X%" knob is a direct overhead multiplier — expect this to
     need its own quota/backoff logic, analogous to how DAMOS actions
     already have `damos_quota`.
   - A cheaper realistic path: keep the design (1 core-level `sampling_addr`
     per merge/split decision) but change **what determines region size**,
     i.e. bias `damon_region_sz_limit()` or the merge threshold in
     `kdamond_merge_regions()` to keep regions of a *targeted* page-type
     smaller (denser sampling) than others — this composes with 7.2 below
     rather than fighting the existing one-sample-per-region model.

### 7.2 "Target specific region types (anon, dma, etc.)" — yes, partially implemented

Confirmed by reading `damon.h:340`–`405` and `ops-common.c:252`
(`damos_folio_filter_match`): **DAMOS filters already exist**, but they
gate **scheme *action* application**, not **monitoring/sampling** — a
filtered-out page is still sampled and counted in `nr_accesses` exactly
like any other page; it's only skipped when a `damos` scheme tries to
`madvise()`/reclaim/migrate it.

```c
enum damos_filter_type {          // damon.h:363
    DAMOS_FILTER_TYPE_ANON,       // folio_test_anon(folio)   — ops-common.c:259-260
    DAMOS_FILTER_TYPE_ACTIVE,     // folio_test_active(folio) — ops-common.c:262-263
    DAMOS_FILTER_TYPE_MEMCG,      // folio's memcg == filter->memcg_id
    DAMOS_FILTER_TYPE_YOUNG,      // vaddr.c has its own PTE-direct fast path: damos_va_filter_young_match, vaddr.c:610
    DAMOS_FILTER_TYPE_HUGEPAGE_SIZE, // folio size in [min,max]
    DAMOS_FILTER_TYPE_UNMAPPED,   // !folio_mapped() || !folio_raw_mapping()
    DAMOS_FILTER_TYPE_ADDR,       // core-layer, splits region at boundary (core.c:1761)
    DAMOS_FILTER_TYPE_TARGET,     // core-layer, matches by target index
};
```

**No `DMA`/`DAMOS_FILTER_TYPE_DMA` exists** — confirmed by grepping
`mm/damon/` for `DMA`/`dma_buf`, zero hits. dma-buf-backed memory isn't
represented as a normal anon/file folio in a process's page tables the
same way, so it wouldn't hit this per-folio filter path at all without
extra plumbing.

Filter evaluation path, two layers (matches the doc comment at
damon.h:352-361):

- **Core-layer filters** (`s->filters`, only `ADDR`/`TARGET`) — evaluated
  in `damos_filter_out()` (core.c:1792), *before* `ops.apply_scheme` is
  even called; can split a region at a filter boundary
  (`damos_filter_match`, core.c:1743).
- **Ops-layer filters** (`s->ops_filters`, everything else) — evaluated
  *inside* `vaddr.c`'s per-page-table-entry walk, e.g.
  `damos_va_filter_out()` (vaddr.c:632), called from both
  `damos_va_stat_pmd_entry` (vaddr.c:900, counts `sz_filter_passed` for
  `DAMOS_STAT`/reporting) and `damos_va_migrate_pmd_entry`/`_pte_entry`
  (vaddr.c:722/762, gates actual migration). **`DAMON_OPS_VADDR` and
  `DAMON_OPS_FVADDR` do NOT support `ANON`/`MEMCG` filters** per the
  damon.h:359-361 comment — those two are only implemented for
  `DAMON_OPS_PADDR` at the `apply_scheme` dispatch level (not shown here,
  see `paddr.c` if pursuing that path); `vaddr.c`'s
  `damos_va_filter_out()` still calls `damos_folio_filter_match()`
  generically, so it's worth re-checking against the current source
  whether that VADDR-vs-PADDR restriction is enforced at commit-time
  (sysfs validation) or silently ignored — didn't chase that further here.

**Practical implication for the stated task:** if the goal is "only
*monitor* (sample) anon/file/dma regions differently" (not just "only
*act on* anon pages once already matched"), the filter mechanism above is
the wrong lever — it's downstream of sampling, applied per-scheme, per-
action. You'd instead need a new concept at the `damon_region`/
`prepare_access_checks` level: e.g. classify each region (or sub-range) by
backing type at `init`/`update` time (`vaddr.c`'s `damon_va_init`/
`damon_va_update`, which already walk VMAs and have `vma->vm_flags`/
`vma_is_anonymous(vma)` available) and store that classification
somewhere reachable from `prepare_access_checks`/`check_accesses` to
skip-or-bias sampling accordingly. That is new region-classification
logic, not a currently-flagged-but-unused code path — there is no dead
"region type" field to just flip on in `struct damon_region` today; it
holds only `ar`, `sampling_addr`, access stats, and `age` (damon.h:76).

### 7.3 Cheat-sheet: which function to touch for what

| Want to change | Touch |
|---|---|
| How many pages/interval a region samples | `__damon_va_prepare_access_check` + `__damon_va_check_access` (vaddr.c) — currently hardcoded to 1 |
| How aggressively regions merge/split (coverage density) | `kdamond_merge_regions`, `kdamond_split_regions`, `damon_region_sz_limit` (core.c) |
| min/max region count bounds | `damon_attrs.min_nr_regions/max_nr_regions` — already exposed, this is what this repo's sweep tool varies |
| Skip an *action* on anon/active/young/hugepage/unmapped pages | Already exists: `damos_filter` + `DAMOS_FILTER_TYPE_*` (damon.h, ops-common.c, vaddr.c `damos_va_filter_out`) |
| Skip *monitoring itself* by page/VMA type (anon/file/dma) | Not implemented — new logic needed in `damon_va_init`/`damon_va_update`/`prepare_access_checks` |
| Add a new filter type (e.g. DMA) | Add enum value in `damon.h:363`, extend `damos_folio_filter_match` (ops-common.c:252) and/or a vaddr-specific matcher like `damos_va_filter_young_match` (vaddr.c:610) if it needs raw PTE access rather than folio flags |
| Safely mutate a *running* context's policy | `damon_call()` (core.c:1479) — never poke `ctx`/region fields directly from outside the kdamond thread |

---

## Part 8 — File/function index (line numbers, this checkout)

**`mm/damon/core.c`**
- Ops registry: `damon_register_ops` 73, `damon_select_ops` 100
- Region CRUD: `damon_new_region` 121, `damon_add_region` 141,
  `damon_destroy_region` 158, `damon_set_regions` 211,
  `damon_split_region_at` 2379
- DAMOS object CRUD: `damon_new_scheme` 377, `damos_new_filter` 269,
  `damos_new_quota_goal` 327
- Context lifecycle: `damon_new_ctx` 524, `damon_destroy_ctx` 568,
  `damon_set_attrs` 713, `damon_commit_ctx` 1235
  (commit_schemes/targets/target_regions helpers 1080-1220)
- Start/stop: `damon_start` 1350, `damon_stop` 1410, `kdamond_fn` 2647
- External IPC: `damon_call` 1479, `damos_walk` 1522,
  `kdamond_call` 2551
- Aggregation: `kdamond_reset_aggregated` 1562,
  `damon_update_region_access_rate` 2915
- Adaptive regions: `kdamond_merge_regions` 2353,
  `kdamond_split_regions` 2437, `damon_region_sz_limit` 1284
- DAMOS apply path: `kdamond_apply_schemes` 2249,
  `damon_do_apply_schemes` 1963, `damos_apply_scheme` 1895,
  `damos_filter_out` 1792, `damos_valid_target`/`__damos_valid_target`
  1644/1658
- Quota: `damos_adjust_quota` 2188, `damos_set_effective_quota` 2138,
  `damon_feed_loop_next_input` 2012
- Interval auto-tune: `kdamond_tune_intervals` 1619

**`mm/damon/vaddr.c`**
- Region init: `__damon_va_three_regions` 120, `__damon_va_init_regions`
  239, `damon_va_init` 280, `damon_va_update` 294
- Sampling: `__damon_va_prepare_access_check` 409,
  `damon_va_prepare_access_checks` 417, `damon_va_young` 540,
  `__damon_va_check_access` 560, `damon_va_check_accesses` 586
- Accessed-bit plumbing: `damon_mkold_pmd_entry` 306,
  `damon_young_pmd_entry` 439 (both delegate to `ops-common.c`'s
  `damon_ptep_mkold`/`damon_pmdp_mkold`)
- DAMOS filters (ops-layer): `damos_va_filter_young_match` 610,
  `damos_va_filter_out` 632
- DAMOS actions: `damon_va_apply_scheme` 990 (dispatch table),
  `damos_madvise` 813, `damos_va_migrate` 839, `damos_va_stat` 962
- Scoring: `damon_va_scheme_score` 1027
- Registration: `damon_va_initcall` 1046 (registers both
  `DAMON_OPS_VADDR` and `DAMON_OPS_FVADDR`)

---

## Part 9 — Things worth re-verifying on the actual HongMeng-side kernel

This guide was built from a fairly recent upstream Linux DAMON (fields like
`addr_unit`, `intervals_goal`, `migrate_dests`, `nr_accesses_bp` moving-sum
are all comparatively new). Before assuming HongMeng's DAMON matches this
1:1:

1. Confirm which `damon_ops_id` HongMeng actually wires up (`VADDR`,
   `FVADDR`, `PADDR`, or a custom one) — that decides which file mirrors
   `vaddr.c` there.
2. Confirm `struct damon_region` has the same fields — if HongMeng is based
   on an older Linux DAMON snapshot, `nr_accesses_bp`/`age` semantics or
   the merge/split thresholds may differ, which changes where a "% sampled"
   patch would land.
3. Confirm whether `damos_filter` / `DAMOS_FILTER_TYPE_ANON` exists at all
   in that tree — if it's an older base, the "already implemented" answer
   in Part 7.2 might not hold there, and the ANON targeting would need to
   be added from scratch rather than reused.
4. Re-run the "no DMA filter type" grep on the actual HongMeng source tree,
   not just this Linux checkout.
