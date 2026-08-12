# Task brief: write the HongMeng-side DAMON guide

You are working inside a trimmed HongMeng OS source tree that contains only
DAMON's **core**, **vaddr**, and **sysfs** implementation files plus their
headers — not a full kernel checkout. Your job is to produce **one new
markdown file** that explains this HongMeng DAMON code the same way
`damon_core_vaddr_guide.md` (included alongside this brief) explains
upstream Linux's `mm/damon/core.c` + `mm/damon/vaddr.c`.

**Read `damon_core_vaddr_guide.md` first**, end to end, before touching the
HongMeng source. It is your **style and depth template**, not a source of
facts about HongMeng — HongMeng's DAMON may be a fork of an older Linux
DAMON snapshot, or diverge in real ways. Where HongMeng's code differs from
what that guide describes for Linux, HongMeng's actual code wins, always.
Never carry over a Linux-specific claim into the new guide without having
independently verified it against the HongMeng source in front of you.

## 1. Why this exists

This guide is not the end goal — it is groundwork for a later step that
estimates how many lines of code a specific policy change would take in
HongMeng's DAMON (adjusting the sampling policy / adding region-type
targeting), then implements it. A reader with zero prior exposure to this
codebase must be able to read your guide start to finish and come out able
to point at the exact function(s) to modify for that change — not just
"understand DAMON" in the abstract.

## 2. Before you write anything

1. **Inventory the actual files first.** Do not assume HongMeng's file
   names, line counts, or directory layout match Linux's `mm/damon/`. List
   what's actually present (core equivalent, vaddr equivalent, sysfs
   equivalent, and every header they `#include` that's also in the trimmed
   tree) and note the real paths/line counts at the top of your guide, the
   same way `damon_core_vaddr_guide.md` opens with the exact checkout and
   line counts it was built from.
2. **Read every file completely**, not excerpts. If a file is large, read
   it in full sequential chunks — do not sample functions and extrapolate
   the rest. Every claim in your output must trace back to a line you
   actually read.
3. **Verify, don't assume.** For every structural or behavioral claim,
   confirm it by reading the actual struct/function, or by grepping the
   tree — the same standard applied throughout this session's Linux guide
   (e.g. the "no DMA filter type" claim there is backed by an actual grep
   with zero hits, not an assumption).

## 3. The checklist — resolve these explicitly, don't skip them

`damon_core_vaddr_guide.md` Part 9 lists specific open questions about
HongMeng that were flagged *without* access to the HongMeng source. Resolve
every one of them explicitly in your guide, with a clear verdict (confirmed
identical / confirmed different — explain how / not applicable):

1. Which `damon_ops_id`(s) does HongMeng actually wire up — is there a
   direct equivalent of `DAMON_OPS_VADDR`/`DAMON_OPS_FVADDR`, or something
   structured differently?
2. Does the region struct (HongMeng's equivalent of `struct damon_region`)
   carry the same fields — in particular, is there a live/moving-sum
   access-rate field like `nr_accesses_bp`, or only a raw counter like
   `nr_accesses`? This directly changes where a "% sampled" change would
   land.
3. Does a DAMOS-style filter mechanism exist at all, and if so, does an
   `ANON`-equivalent filter type exist? Confirm with an actual grep/read,
   not by assuming the Linux enum carries over.
4. Re-run the "is there a DMA/dma-buf-aware filter or region type anywhere"
   search on the actual HongMeng tree — report the result either way (found
   at `file:line`, or confirmed absent by grep).

Add any other divergence you notice along the way, even if not on this
list — the point of this checklist is a minimum bar, not a ceiling.

## 4. Scope difference from the Linux guide: sysfs is now in scope

The Linux guide explicitly left `mm/damon/sysfs.c` uncovered (see its Part 1
diagram, marked "not covered here", and Part 3's sysfs sections which only
went as deep as answering one specific follow-up question). Your trimmed
source tree includes a sysfs-equivalent file — **it must be a first-class
part of your guide**, not a footnote. At minimum, cover:

- How userspace-supplied fixed addresses reach the region list (the
  HongMeng equivalent of the Linux guide's Part 3 "external path" section)
  — actual function names and call chain, not "presumably similar to
  Linux".
- Whether HongMeng's sysfs (or equivalent config interface) enforces the
  same constraints Linux's does (e.g. Linux requires regions sorted by
  ascending address, rejecting overlaps with `-EINVAL` — check whether
  HongMeng's interface has an equivalent validation, and where).
- How policy/attribute changes (equivalent of `damon_set_attrs`,
  `damon_commit_ctx`) reach a *running* monitoring thread safely — is there
  an equivalent of `damon_call()`'s IPC mechanism, or does HongMeng do this
  differently?

## 5. Required structure and quality bar

Follow the structural lessons already applied in `damon_core_vaddr_guide.md`
(it went through several rounds of revision this session specifically to
fix these things — don't reintroduce the problems it started with):

- **Table of contents at the top**, nested bullets with working hyperlinks
  to every heading, mirroring the actual heading hierarchy.
- **Every substantial explanation is its own heading** (H2 for major parts,
  H3 for structs/subsections, H4 for "deep dive" explanations of tricky
  mechanics) — never bury a real explanation inside an unlabeled blockquote
  that doesn't show up in the table of contents.
- **Bottom-up vocabulary first**: struct-by-struct, each building on the
  previous, before any control-flow explanation.
- **Then**: how the region list first comes to exist (both the automatic
  path, if HongMeng has one, and the sysfs/external path) → low-level
  region primitives → the main monitoring-thread loop, statement by
  statement → any cross-thread IPC mechanism → task-oriented synthesis.
- **Concrete worked examples for anything non-obvious** — this session's
  Linux guide had to add numeric traces (e.g. a tick-by-tick table for how
  an access-rate field updates) after a first pass that only described the
  mechanism in prose turned out to be unclear. Don't wait to be asked
  twice — if a mechanism involves a formula, state or arithmetic across
  multiple steps, trace it with real numbers the first time.
- **File:line citations for every function/struct you name**, using
  HongMeng's real paths and line numbers (never copy a Linux line number
  across).
- **A closing function/file index** (mirroring the Linux guide's Part 8) —
  every function you referenced, grouped by file, with line numbers.
- **A closing task-application section** (mirroring the Linux guide's
  Part 7) that maps the two concrete goals — "adjust the percentage of a
  region's pages sampled" and "target monitoring by region type
  (anon/dma/etc.)" — onto HongMeng's actual functions and structs, plus a
  cheat-sheet table ("want to change X → touch Y") to directly feed the
  next pipeline step (estimating lines of code for the change).

## 6. What "done" looks like

A reader who has never opened this HongMeng source tree should be able to
read your guide alone, start to finish, and by the end: understand the full
monitoring lifecycle (region setup → sampling → aggregation → policy
application), know exactly which functions implement the sampling density
and region-type-filtering questions from Part 7 of the reference guide, and
have an explicit, sourced answer (not a guess) for every item in Section 3's
checklist above.

Save the result as a new markdown file (e.g.
`damon_hongmeng_guide.md`) alongside this brief.
