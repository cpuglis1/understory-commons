# ADR-002: Donor surface + ProfileSnapshot

**Date:** 2026-05-28
**Status:** Proposed
**Authors:** Chris (planning session: Opus 4.7)

## Context

Build-sequence step 4 of `understory_architecture.md` is the first work that
crosses the coordinator/donor boundary: a public program page fed by a
published, verified snapshot of operational data. The architecture doc calls
this "your networking demo" — the point where the loop is visible end to end
(log a session → it shows as verified data on a public page).

This trips three CLAUDE.md escalation triggers at once, which is why it gets an
ADR before code:

1. **Schema change touching more than one table** (a new `ProfileSnapshot`
   model + slug fields on existing models).
2. **It modifies the verification-chain / PII-minimization posture** — it is the
   first thing that exposes coordinator-derived data to an unauthenticated
   public surface (core invariant #1).
3. **New integration design** — the donor surface is a genuinely separate
   surface with its own dependency rules (architecture §3).

The actual codebase has diverged from the architecture doc's sketched layout
(no `dashboard`/`discovery`/`ai`/`theme` apps yet; the coordinator attendance
loop lives in the `attendance` app, not a `dashboard` app — see the
2026-05-28 attendance-UI handoff). This ADR records the decisions for the
donor surface specifically, adapting the doc to what exists.

## Decision

### 1. A new `discovery` app houses the donor surface

The coordinator/donor separation is a hard invariant (architecture §3 dependency
rule + core invariant #1), not a stylistic split. A second app is the mechanism
that physically prevents the donor surface from reaching coordinator working
data: `discovery` may import from `core` only, never from `attendance` or
`accounts`. This is the "second use case" that justifies the app boundary under
CLAUDE.md's "no new abstractions" rule — it is not premature; the separation is
the product invariant.

`discovery` is browse-only and unauthenticated in V1 (CLAUDE.md default: donor
auth does not exist yet).

### 2. `ProfileSnapshot` is an append-only, versioned, published projection

```python
class ProfileSnapshot(TimestampedModel):
    id = UUIDField(pk)
    program = FK(core.Program, on_delete=PROTECT, related_name="snapshots")
    version = PositiveIntegerField()                 # 1, 2, 3… per program
    status = CharField(choices=[DRAFT, PUBLISHED, WITHDRAWN])
    published_at = DateTimeField(null=True)          # set once, on publish
    published_by = FK(accounts.User, on_delete=PROTECT, null=True)
    supersedes = FK("self", null=True, on_delete=PROTECT)  # prev version
    payload = JSONField()                            # frozen donor-facing view
    coverage_start = DateField()                     # derivation window
    coverage_end = DateField()
```

- **Append-only:** a published snapshot is immutable. Re-publishing creates a new
  version row that `supersedes` the prior one. Withdrawal is a new `WITHDRAWN`
  version, never a delete or mutation. This matches the existing
  `AttendanceRecord` / `CorpusEvent` append-only pattern and honors invariant #3.
- **"Current public" = latest `PUBLISHED` version per program** whose successor
  is not `WITHDRAWN`. The donor surface reads only this.

### 3. The publish service recomputes numbers from the log — it never accepts them

This is the rule that keeps invariant #1 intact across the boundary:

- The snapshot builder computes every **numeric** metric by calling the existing
  derived-metric queries (`attendance.queries.program_month_stats` /
  `session_headcount`) over `[coverage_start, coverage_end]`. It never reads a
  metric value from a form or client payload.
- The coordinator controls **which** metrics to publish and edits **descriptive
  prose** (program summary, org blurb) — but cannot type a number that reaches
  donors.
- Every metric in `payload` carries `provenance: "derived"` and records its
  derivation window, so the donor page can render a provenance badge and the
  system can re-derive the number from the immutable `AttendanceRecord` log.

### 4. Lean now: no `MetricDefinition` / `OutcomeMetric` vocabulary yet

The architecture doc sketches a standardized metric catalog. That catalog exists
to make programs **comparable** (build-sequence step 6, "Compare"). A single
program page does not need it. We freeze the already-derived attendance numbers
(sessions held, headcount/attendance trend) directly into `payload`.

The `MetricDefinition`/`OutcomeMetric` layer lands when Compare is actually built
— that is its real second use case. Building it now is premature generalization
(CLAUDE.md "no new abstractions without a second use case").

### 5. Snapshots build synchronously on publish — no background queue

Snapshot construction is a handful of DB aggregates, not an LLM call. It runs in
the request on the publish action. The background-job queue decision (Django-Q2
vs RQ, still open in CLAUDE.md) is deferred to step 5 (AI module), where it is
actually needed.

### 6. Public URLs need slugs

`core.Program` and `core.Organization` get a unique `slug`. Public program page:
`/programs/<program-slug>/`. Slugs are generated on save from name; collisions
suffixed. (Single-table additions, but listed here because they are part of the
boundary-crossing surface.)

## Consequences

- The donor surface can only ever show numbers that a coordinator's real logged
  activity produced, and only after a deliberate publish action. There is no code
  path from a public view to a writable coordinator row.
- Publishing is reproducible and idempotent: the same window over the same
  immutable log yields the same payload (invariant #4).
- The public page is eventually-consistent by design — it shows the last
  published snapshot, not live working data. A coordinator's unpublished edits
  are never visible. This is the "deliberate publish, never a live leak"
  property the architecture leans on.
- `payload` is denormalized JSON. If we later need to query across snapshots
  (e.g. for the discovery feed / Compare), we add indexed columns or a read model
  then — not now.
- PII posture unchanged: `payload` contains program/org descriptive text and
  derived counts only. Participant `display_name`s never enter a snapshot. A test
  locks this (see plan).

## Alternatives considered

- **Build the full `MetricDefinition`/`OutcomeMetric` vocabulary now.** Rejected
  for V1: it is standardization machinery whose only consumer (Compare) is two
  steps away. Deferring keeps the schema honest and the slice shippable. The
  `provenance` concept we *do* need is captured per-metric in `payload`.
- **Put donor views in the existing `attendance` app.** Rejected: it would let
  the donor surface import coordinator working models directly, defeating the
  invariant the separation exists to enforce. The app boundary *is* the control.
- **Donor surface reads live derived queries instead of frozen snapshots.**
  Rejected: it would expose unpublished working data and make the public page a
  live leak rather than a deliberate publication. Snapshots are the difference
  between "verified, published" and "self-reported live feed."
- **Build snapshots as background jobs.** Rejected as premature: the computation
  is cheap and synchronous is simpler. Revisit only if a snapshot ever needs an
  LLM-drafted narrative section (that would be a step-5 concern).
- **Model the snapshot as another append-only event in a log.** Considered for
  symmetry with `AttendanceRecord`/`CorpusEvent`. Rejected as over-built: a
  versioned row with `supersedes` gives the same immutability guarantee without a
  materializer. The underlying *attendance* events remain the source of truth;
  the snapshot is a published projection of them.
