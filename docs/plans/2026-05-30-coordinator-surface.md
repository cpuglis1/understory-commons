# Plan — Coordinator surface: home/dashboard as launchpad

**Date:** 2026-05-30
**Planning model:** Opus 4.8
**Implementation model:** Sonnet 4.6 (switch after this plan is approved)
**Phase:** Coordinator surface (the actual product — admin automation for program staff)
**Supersedes scaffolding:** the thin coordinator pages from step 4 (list/detail/publish/new)
were demo scaffolding for the donor surface, not a designed coordinator experience.
This phase replaces that with a real one.

---

## The fieldwork test (required before approval)

When Matthew Ratz (Passion for Learning) logs in Monday morning, today he sees a
bare list of program names on an unstyled page. After **slice 1** ships, he lands
on a coordinator home that, in one glance, tells him which of his programs ran
recently, what he's logged, and what's outstanding — and gets him **one tap** from
"log today's attendance" for any program. He is not asked to look at a dashboard for
its own sake; the home exists to route him into the work. The data shown is real
logged activity (attendance events, published snapshots), never vanity metrics.

> Honest caveat carried from planning: a dashboard that shows numbers but offers no
> action would fail this test. Slice 1 is scoped as a **launchpad**, not a readout.
> Its CTA ("Log attendance") is the reason it exists; slice 2 builds the screen that
> CTA opens. If slice 1 ends up being charts-without-actions, it is misscoped — stop.

---

## Guardrails (unchanged, do not break)

1. **Verification chain.** Anything the dashboard shows as a number traces to a logged
   event (attendance records via `attendance.queries`, published snapshots). No new
   metric source.
2. **PII minimization.** Dashboard shows program-level counts and `display_name` only
   where the coordinator already sees it in their own workflow (their own facilitators,
   their own participants list). No new PII fields, no contact info, no delivery.
3. **Append-only.** Recent-activity feed reads the event/record stream; it never mutates.
4. **`programs_visible_to(user)`** is the only program scoping. Coordinators see their
   org; facilitators see assigned programs. The home must respect role.

---

## Slice 1 — Coordinator shell + home/dashboard (the launchpad)

**Deliverable a coordinator could use:** Matt logs in, lands on a styled home showing
his programs with a "Log attendance" button on each, a recent-activity strip, and a
"needs attention" hint (e.g. "no attendance logged this week"). One tap reaches the
attendance flow (slice 2 stub until then; until slice 2, the button can open the
existing manual path or a clearly-labeled "coming next" target — decide at build time,
do not fake data).

Scope:
- **`templates/base.html` → real coordinator shell.** Replace the bare shell with a
  layout that has: org name, logged-in user + role, a minimal nav, and a content block.
  Keep HTMX. Mobile-first but desktop-fine. No SPA, no CSS framework dependency unless
  it's a single vendored file (ADR if you add one).
- **`/coordinator/` home view** (`accounts` or a new `coordinator` view module — decide;
  leaning `attendance` since that's where the work is). Magic-link login already lands
  on `attendance:program_list`; repoint it at the new home.
- **Home content, all from real data:**
  - Programs the user can see (`programs_visible_to`), each with: name, site label,
    last-attendance-date, last-published state, and a primary **Log attendance** CTA.
  - **Recent activity** strip: last ~10 events across the coordinator's programs
    (attendance logged, snapshot published) with actor + timestamp.
  - **Needs-attention** hint: programs with no attendance record in the trailing 7 days.
- **Publish/preview/new-program** stay reachable but demote from "the page" to actions
  within a program's context.

Tests required before merge:
- Home requires auth (403 unauth).
- Coordinator sees only their org's programs; facilitator sees only assigned.
- Recent-activity feed shows a real logged attendance event and a real publish event,
  and shows nothing fabricated when there's no activity.
- No `display_name` of a participant leaks into any context the coordinator wouldn't
  already see in their own workflow.
- Login redirect lands on the new home.

Explicitly NOT in slice 1: the attendance-capture screen itself (slice 2), AI parse,
parent-update drafting, timesheets.

---

## Slice 2 — Attendance capture (the #1 validated pain)

The screen the slice-1 CTA opens. Manual entry first; AI free-text parse
(`AttendanceRecord.LLM_PARSE` path) as a fast-follow within the slice. This is where
the real product value lands. Detailed plan deferred until slice 1 is in and we've
re-run the fieldwork test against the actual shell.

Sketch only (do not build from this — it gets its own plan section once slice 1 lands):
- Pick/confirm today's session for a program (create `Session` if absent, idempotent).
- Manual roster check-off → append `AttendanceRecord`s (present/late/absent/excused).
- Free-text box → LLM parse → proposed records the coordinator confirms before commit.
  The prompt is the contract (Opus reviews the prompt before scaling calls).

---

## Deferred (named so they don't get improvised in)

- Permission/release form tracking, timesheets, parent-update drafting, photo/testimonial
  intake, satisfaction surveys — all later coordinator-surface slices.
- Background queue (synchronous is fine at current scale).
- Org-level public profile page (its own step).
- Discovery feed / Compare (donor-surface step 6).

---

## Why this is plan-then-build, not improvise-more

Step 4 shipped the donor surface correctly, but its coordinator pages were reactive
scaffolding. The coordinator surface is the heart of the product and a multi-slice
effort; continuing to add endpoints ad hoc is the dominant failure mode CLAUDE.md warns
against. This plan draws the line: slice 1 = a real, usable launchpad; slice 2 = the
attendance capture it points to; everything else is named and deferred.

**Next action after approval:** `/clear`, switch to Sonnet, implement slice 1 against
this plan. If slice 1 reveals the launchpad framing is wrong, stop and update this doc.
