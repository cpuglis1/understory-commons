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

## Slice 2 — Session wrap (the V1 multiplier)

> ⛔ **SUPERSEDED 2026-05-31 by `docs/plans/2026-05-31-session-guide.md` + its ADR.** The
> session-guide brief (`docs/design/2026-05-31-session-guide-concept.md`) is now the source of
> truth and **there is no LLM in V1**. Everything below that depends on AI —
> the parent-update draft (§2.5), the coordinator AI-parse (§2.6), and the
> `commons/ai/client.py` thin client — is **retired, not built**. What carries forward (tap-first
> attendance, append-only/idempotent commit, today's-session `get_or_create`, the slug seam,
> emergent + "+ Add someone" roster) is restated and extended in the new plan. The new build also
> *re-introduces hours/pay* (the new pay-prep byproduct), which this section had dropped. Read the
> new plan, not this section, for the current build. Kept for provenance only.

**Date this section written:** 2026-05-31. **Planning model:** Opus 4.8.
**Supersedes** the earlier "attendance-only" Slice 2 sketch on Chris's call: a tool that
*only* does attendance isn't worth a busy facilitator maintaining. Slice 2 is the
**session wrap** — one ~15-second end-of-session habit that captures **attendance +
activity**, and from that single input fans out **the weekly number, the progress
record, and a drafted parent update**. Net tools go *down*: the facilitator logs once;
chores that were separate (tally the number, write the parent note) get deleted, not
added.

**The V1 multiplier, stated exactly:**
- **Capture (rides into the one moment):** attendance (tap-first, deterministic) +
  activity (one-tap type chip + optional voice/text color).
- **Payoff that falls out, built in V1:** an AI-drafted **parent/family update**
  (generation only — coordinator copies it into their own group text). This is where AI
  earns its place.
- **Three of the seven CLAUDE.md admin targets from one capture:** attendance, progress
  check-in, family communication.

**Explicitly dropped from V1 (Chris, 2026-05-31):** facilitator **hours / timesheet /
payroll**. Without a payroll consumer, capturing hours would be logging data for its own
sake — a thing the product forbids. The *architecture* still permits it later; the
*field* is not on the V1 screen. (§2.13 keeps the door open.)

---

### 2.1 The fieldwork test (re-run for the multiplier, required before approval)

A facilitator finishes a 90-minute after-school film session — 14 kids, phone in pocket.
Today there is **no method**; nobody records who came, and Matthew Ratz can write no
weekly number and no parent update. After Slice 2: at session end the facilitator opens
the program on their phone, taps **"Mark all here,"** taps **Marcus → absent**, taps the
**"Filming"** chip, optionally thumbs or dictates *"shot the final scene, kids ran their
own lighting,"* and taps **Save** — ~15 seconds, no grid. Monday, Matthew opens the
dashboard: the week's attendance number is *there*, traced to that facilitator's logged
session. He taps **"Draft this week's update,"** gets a warm paragraph built from the
week's three sessions, tweaks one line, and pastes it into the parents' group text.
**Two chores — the number and the parent note — done from one 15-second-per-session
habit, with no spreadsheet and nothing written from scratch.** That fan-out is the slice.

---

### 2.2 The "isn't-manual-input" answer, settled (tap-first; AI on the prose)

A 14-row check-off grid is manual input; an AI that *guesses* a known roster is a new way
to be wrong. So:

- **Attendance is tap-first and deterministic.** The roster is a set of name chips. The
  common case ("everyone came") is a single **explicit** "Mark all here" tap; exceptions
  are 1–2 taps. AI is *not* on this path — a bounded, known roster is exactly where taps
  beat a parse and where being wrong (marking the wrong kid absent) is worst.
- **AI is reserved for unbounded prose, where it's additive and low-stakes:** the
  **parent-update draft** (2b) and the **coordinator batch-entry** path (2c) that turns a
  facilitator's free-text message into a wrap.

**Two users, two modes, one data model:**
- **Facilitator, in the room, on a phone → tap-first wrap (2a).** The hero gesture.
- **Coordinator, at a laptop, batching from facilitators' texts → free-text/voice → AI
  parse → the *same* confirm roster (2c).** This is where the old plan's "AI parses
  attendance" idea actually belongs — the coordinator's accelerator, not the
  facilitator's primary. It never auto-commits; a human confirms.

**"Mark all here" is an explicit gesture, not a pre-checked default — deliberately.** A
silently-pre-present roster lets a Save-on-autopilot record 100% attendance nobody
verified, and attendance-rate is the one number donors see (invariant #1). One conscious
tap keeps the speed *and* the attestation.

---

### 2.3 The capture screen (2a) — what's on it

Mobile-first, desktop-fine; matches the locked dashboard tokens
(`docs/design/2026-05-30-coordinator-dashboard.md`).

1. **Header:** program name + today's date. Opening the screen **resolves today's
   session** — `get_or_create` on `(program, scheduled_date=today)`, idempotent (honors
   the existing `unique_session_per_program_date` constraint; invariant #4). The date is
   **editable** for backfill ("I forgot Tuesday") — same get_or_create on the chosen date.
2. **Attendance roster:** name chips from the org's carried-forward `Participant` set
   (§2.4). **"Mark all here"** sets all to present; tap a chip to toggle
   **present ↔ absent**. **V1 statuses = present / absent only** (the model already
   carries `late`/`excused`; they're just not surfaced — add them the day a CBO asks).
   **"+ Add someone"** creates a `Participant` (`display_name` only) on the fly for a new
   kid.
3. **Activity:** a row of one-tap **activity-type chips** (generic V1 set — e.g.
   *Project work · Skill practice · Discussion · Field trip · Showcase · Other*) gives a
   structured **progress** signal in one tap; an optional **"What did you do today?"**
   text box (phone-keyboard mic for voice) adds color. The chip is the structured datum;
   the text is enrichment. Per-program *custom* phase vocabularies are deferred — a
   generic set avoids a premature taxonomy until fieldwork shows what phases real programs
   actually name (§2.12).
4. **Save wrap:** appends attendance records + writes the activity onto the session;
   redirects to the dashboard with a confirmation count ("14 present · activity logged").

No hours field (dropped). No photo (deferred, §2.12).

---

### 2.4 Roster — emergent, then carried-forward (unchanged principle)

Honors `[[feedback_workflow_fit]]` (no pre-built rosters; single `display_name`):

- **First-ever session:** roster is **empty**. The facilitator adds kids via "+ Add
  someone" (or, via 2c, names them in free text); each becomes a `Participant` on save.
  Nothing is pre-built.
- **Later sessions:** the org's accumulated `Participant` set already holds those names
  (they emerged from prior use); the screen shows them as chips. This is *reuse of
  emerged names*, not upfront roster-building — the thing Chris rejected was the latter,
  not this.
- **No silent default to argue about.** With present/absent + an explicit "Mark all
  here," the carried-forward chips render **neutral** until the human acts. (This retires
  the old §2.4 A/B/C decision — the explicit-gesture model makes it moot.)

---

### 2.5 The AI contract — parent-update draft (2b) (Opus designs the prompt; the prompt is the contract)

This is now the **hero AI feature** — it replaces "AI parses attendance" as where the
model earns its place. Through the thin module `commons/ai/client.py` (**does not exist
yet — building it is part of 2b**; default Sonnet 4.6 per `[[project_arch_decisions]]`).
One call per draft, weekly cadence → far under the $1/program/month target.

**Input to the model (aggregate only — no child identity):**
- Program name; the week's date range.
- Per session in the week: `scheduled_date`, the **activity-type** chip, the **activity
  note** (free text), and an **attendance headcount** ("12 of 14 present").
- **No participant `display_name`s.** The V1 parent update is a **group** message ("This
  week the film club…"), not a per-child note — so child identity never enters the prompt
  or the output. This is the bright line that keeps the draft PII-free (invariant #2).

**Output:** a short, warm, copy-pasteable group update (1–2 short paragraphs, plain text)
suitable for a group text / Facebook group. The coordinator edits and copies it into
their own channel.

**Hard invariants on this path:**
- **Generation only — no delivery.** No Twilio/Mailgun/etc. (stack invariant). The tool
  produces text; the human sends it.
- **No child PII in or out.** Aggregate activity only; no names, no contact info.
- **Human reviews before use** — it's a draft, never auto-sent.
- **Derived from real logged sessions** — built from logged wraps, not fabricated. It is
  *not* a donor-facing verified metric, so it does not enter the verification chain /
  snapshot; it's an assistive artifact. The verified numbers remain the append-only
  `AttendanceRecord`s.
- **Graceful degradation.** No sessions this week → honest "nothing logged this week to
  draft from," never a hallucinated update. Model error / invalid output → show an error,
  never a crash, never a fabricated paragraph.
- **Logged for cost/audit:** record the generation event (program, week, `llm_request_id`,
  actor, timestamp). Do **not** persist the draft body in V1 (regenerate on demand) — no
  reason to store generated copy.

---

### 2.6 The AI contract — coordinator batch-entry parse (2c)

The second-user accelerator. Reuses `commons/ai/client.py`. A coordinator pastes a
facilitator's text ("all here except Marcus, we filmed the final scene"); the model
returns a **proposed** roster + activity that pre-fills the **same 2a confirm screen**;
the coordinator corrects and commits.

**Output contract (structured JSON, validated before use):**
```
{
  "records": [{"name":"<as written>","participant_id":"<uuid|null>",
               "status":"present|absent","confidence":0.0-1.0}],
  "new_names": ["<unmatched names → proposed new Participant>"],
  "ambiguous": [{"name":"...","candidates":["<id>","<id>"]}],
  "activity_type": "<one of the chip set | null>",
  "activity_note": "<free-text summary | null>",
  "exception_style": true|false
}
```

**Matching rules (deterministic intent; the model executes them):** tolerant match to
`display_name` (nickname / first-name / first + last-initial, because that's how
facilitators refer to kids); no match → `new_names`; two plausible → `ambiguous` (the
screen disambiguates, never a silent guess); "everyone except…" → `exception_style=true`
and the screen marks the rest present on the human's confirm.

**Hard invariants:** human confirms before any write (the parse never commits an
`AttendanceRecord`); committed records carry `source=llm_parse`, `raw_input` = verbatim
text, `llm_request_id`; `display_name` only (a last name in the text is stored as the
in-the-moment identifier, no structured split — invariant #2); parse failure degrades to
the manual 2a screen; idempotent confirm (the per-render key no-ops a re-POST; re-parsing
doesn't double-create).

---

### 2.7 Data model — what the build adds (one table, ≤two fields)

Grounded in the real models (read 2026-05-31):
- **Attendance: no schema change.** `AttendanceRecord` already enforces append-only at the
  model level (`save()` raises on update) and carries `status`, `source`
  (`llm_parse`/`manual_form`), `recorded_by`/`recorded_at`, `raw_input`, `llm_request_id`,
  `submission_idempotency_key`. Manual *and* parse paths already have a home.
- **Activity: add to `Session`** (currently `program`, `scheduled_date`, `notes`):
  - `activity_type` — `CharField(blank=True, choices=<generic V1 set>)`.
  - reuse the existing **`notes`** field for the free-text/voice activity color (label it
    "What did you do today?" in the UI; confirm `notes` isn't already surfaced elsewhere
    before repurposing — else add `activity_note`).
  - `Session` is mutable metadata (no append-only `save()` guard, unlike `AttendanceRecord`
    / `ProfileSnapshot`), so storing activity here is consistent. Activity is **not** yet a
    donor-published verified metric, so it doesn't need event-sourcing. **If activity ever
    becomes a published donor metric, move it to the append-only treatment — escalate then.**
- **Participant: no change** (`display_name` only; `merged_into` already exists for dedupe).
- This is a **one-table, ≤two-field** migration. (A schema change is Opus territory — which
  is why it's specified here.)

---

### 2.8 Routing reconciliation & today's-session resolution

- Keep the merged **slug** convention. The wrap upgrades the live **Beta stub**
  `attendance:attendance_log` at `programs/<slug>/log/` into the real 2a screen.
- Scope every entry through `core.queries.programs_visible_to(user)` (**confirmed
  2026-05-31**: coordinator → `Program.objects.filter(organization=user.organization)`;
  facilitator → `user.facilitated_programs.all()`). A slug outside that queryset → **404**.
- Today's session via `get_or_create((program, scheduled_date=today))`; editable date for
  backfill; both idempotent.
- The archived uuid-based loop (`feat/attendance-coordinator-ui`, `da53963`) is the
  **starting code** for the append-only/idempotent write — its logic carries over; only
  routing (→ slug) and the screen shape (→ tap-first wrap) change.
- **Parent-draft** lands as its own program-/week-scoped view, surfaced from the
  dashboard's **Family comms** tool entry (today `Soon` → becomes `Beta` after 2b) and
  from the program context.

---

### 2.9 Append-only & idempotency (invariants #3 / #4, enforced)

- Commit **appends** `AttendanceRecord`s and **only writes a participant whose status is
  new or changed** vs. their latest record for that session (re-confirming an unchanged
  roster writes nothing). The model's `save()` guard makes mutation impossible by
  construction.
- A correction after commit **appends** a new record (last-wins on read); the prior is
  preserved.
- Read-side metrics (`session_headcount`, `program_month_stats`, the dashboard's
  `org_stats`) recompute from the log — derived, never stored.
- The wrap submit carries the per-render `submission_idempotency_key`; a re-POST
  (double-tap, refresh, back) writes nothing. Parse re-runs don't double-create.

---

### 2.10 Sub-slices (each ends with a usable thing)

**2a — Tap-first session wrap (no AI). Ships standalone — core V1.**
The 2a screen on the slug seam: today's-session resolution, tap-first roster ("Mark all
here" + present/absent toggles), emergent roster + "+ Add someone," activity-type chips +
optional note, append-only idempotent commit, redirect with confirmation. The
`Session.activity_type` migration. *Deliverable:* a facilitator logs a session on their
phone Monday — attendance **and** progress, one screen, ~15s.
- Tests: append-only (unchanged status writes nothing); idempotent re-POST; emergent
  roster (first session, no pre-build); "+ Add someone" mid-program; scoping
  (facilitator/coordinator/cross-org 404); PII probe (`display_name` only); today's-session
  get_or_create idempotent; correction appends not mutates; present/absent toggle;
  activity persisted on the session.

**2b — Parent-update draft (AI, the multiplier payoff). On top of 2a — core V1.**
`commons/ai/client.py` (thin Sonnet wrapper) + the §2.5 prompt; the "Draft this week's
update" view/screen; generation-only display + copy; log the generation event.
*Deliverable:* one tap turns the week's wraps into a parent note the coordinator pastes
into their group text — the comms chore is gone, and the AI differentiator is proven.
- Tests: draft derives from real logged sessions; **no child `display_name` in prompt or
  output (critical PII probe)**; generation-only (no delivery path exists); empty week →
  honest "nothing to draft"; model failure degrades gracefully (no crash, no fabricated
  text); single call (cost).

**2c — Coordinator batch-entry parse (the second-user accelerator). Reuses 2b's client —
in V1 if build time allows, else immediate fast-follow.**
"Add from a text" → §2.6 parse → pre-fills the 2a confirm screen → human corrects →
commit with `source=llm_parse`. *Deliverable:* Matt enters a week of facilitator texts in
minutes; the two-user model is whole.
- Tests: dump → roster statuses; new name → proposed `Participant`; ambiguous → flagged,
  not auto-resolved; **human-confirm-required (never auto-commits)**;
  `source`/`raw_input`/`llm_request_id` persisted; parse failure → manual; re-parse no
  double-write.

2a + 2b are the V1 multiplier and prove the AI differentiator (via the parent draft); 2c
completes the two-user design and can slip to a fast-follow without descoping the
multiplier.

**Aesthetic:** every screen is a member of the locked design system
(`docs/design/2026-05-30-coordinator-dashboard.md`) — mostly white, hairline borders,
black primary buttons, Inter UI, tabular-nums, status pills, green ✓. Not a new look.

---

### 2.11 Dashboard tie-ins (follow-on wiring, not a re-spec)

After this slice the Slice-1.5 dashboard shifts: Tools-menu **"Log attendance" (Beta) →
"Session wrap" (Live)**; **"Family comms" (Soon) → (Beta)**; needs-attention gains
**"N sessions this week have no wrap"**; the activity-type data becomes available to the
(later) donor-surface read-side. Small wiring changes, listed so the build expects them —
not a redesign.

---

### 2.12 Explicitly NOT in Slice 2 (named so they aren't improvised in)

- **Hours / timesheet / payroll** (dropped by Chris — no V1 consumer; would be logging for
  its own sake).
- **Photo / testimonial intake** — same moment, but student faces cross the PII boundary;
  needs its own ADR + release-gate. Design the seam, build later.
- **Per-program custom phase taxonomy** (generic chip set in V1; custom deferred to a
  second use case).
- **Late / excused statuses** (present/absent in V1; the model already holds them — surface
  on CBO request).
- **Release/permission tracking & gap-flags; grant-report section drafting** — later
  coordinator-surface slices.
- **Message delivery of any kind** (generation only — stack invariant).
- **In-app browser speech recognition** (phone-keyboard mic only).
- **Background queue / async AI** (synchronous is fine at this scale).
- **Donor-surface snapshot changes** (read-side already consumes attendance; activity
  feeding the snapshot is a later read-side step).
- **Structured participant name fields** (PII boundary unchanged).

---

### 2.13 Open items for Chris (don't block 2a; confirm before 2b/2c)

1. **Hours:** confirmed dropped from V1. (If you later want hours retained as an optional
   one-tap field for grant-report/payroll use, say so — it returns with the rollup
   deferred.)
2. **Activity chips:** OK to ship a **generic** activity-type set in V1 and defer
   per-program custom phases? (Recommended — avoids a premature taxonomy.)
3. **2c placement:** build coordinator-parse inside V1 if time allows, else as the
   immediate fast-follow? (Recommended.)

---

## Deferred (named so they don't get improvised in)

- Permission/release form tracking, timesheets/payroll, photo/testimonial intake,
  satisfaction surveys — all later coordinator-surface slices. (Parent-update drafting
  moved *into* Slice 2 as the multiplier payoff — see §2.5.)
- Background queue (synchronous is fine at current scale).
- Org-level public profile page (its own step).
- Discovery feed / Compare (donor-surface step 6).

---

## Why this is plan-then-build, not improvise-more

Step 4 shipped the donor surface correctly, but its coordinator pages were reactive
scaffolding. The coordinator surface is the heart of the product and a multi-slice
effort; continuing to add endpoints ad hoc is the dominant failure mode CLAUDE.md warns
against. This plan draws the line: slice 1 = a real, usable launchpad; slice 2 = the
session wrap it points to (attendance + activity → parent-update draft); everything else
is named and deferred.

**Next action after approval:** `/clear`, switch to Sonnet, implement slice 1 against
this plan. If slice 1 reveals the launchpad framing is wrong, stop and update this doc.

---

## Slice 1.5 — Director dashboard (supersedes the slice-1 launchpad home)

**Date added:** 2026-05-31. **Why:** slice 1 shipped, and the launchpad framing
*was* wrong — Chris's read was "it looks like an attendance app." The home is now
redesigned as a front-facing **education-director command center**. Full design +
locked aesthetic: `docs/design/2026-05-30-coordinator-dashboard.md`; approved static
mockup: `docs/design/mockups/coordinator-dashboard.html`. This slice replaces the
slice-1 home with that dashboard, wired to live data. The slice-1 guardrails
(verification chain, PII-light, `programs_visible_to` scoping, append-only reads)
are unchanged and re-tested here.

**Deliverable a director could use:** Matt logs in and lands on a clean, mono-classy
dashboard — org-level verified stat cards, a needs-attention triage queue, a programs
grid, and a cross-tool activity feed — with a top-bar **Tools ▾ mega-menu** that
presents the whole admin platform (attendance, forms, payroll, family comms, progress,
funder/network). It reads as a platform, not an attendance app.

### Scope

**A. App shell (`templates/base.html`)** — rebuild as the mono-classy top bar:
- Pinyon Script wordmark (Google Fonts) → home; nav: Dashboard, Programs, **Tools ▾**.
- **Tools mega-menu**, six categories. Each sub-tool carries a `Live / Beta / Soon`
  pill. **Honesty rule: only Live/Beta items are links; Soon items are muted,
  non-interactive rows** (you can see the roadmap, you can't click into nothing).
  - Live: Facilitators & invites → `accounts:facilitator_new`.
  - Live (program-scoped, route via Programs list): Publish public profile, Public
    program page.
  - Beta: Log attendance → existing `attendance:attendance_log` stub (interim admin
    path works).
  - Soon (non-link): roster/history, participation trends, all Forms, timesheets,
    payroll, all Family comms, all Program progress, grant-report sections, find
    grants, exports.
- Account chip: avatar (initials) + name + role, **static** (no sign-out this slice —
  no login landing page exists yet to return to; logout deferred with that work).
- Inter for UI; tabular-nums for figures; hairline borders; black primary buttons.

**B. Dashboard home (`attendance:home`)** — all numbers from logged events:
- **Stat cards** (period-scoped): Active programs (count), Students reached ✓,
  Sessions held ✓, Attendance rate ✓ (present+late ÷ all records; `—` when no
  records), Profiles live ✓ (programs with a current published snapshot). **Forms
  outstanding → honest empty `—`** (no forms tool yet; not a fabricated number).
- **Period selector** — functional: This week / This month (default) / All time, via
  `?period=`. Drives every ✓ card and the programs grid.
- **Needs attention** — real signals only: (1) no attendance in trailing 7 days →
  links to its `attendance_log`; (2) published profile stale (>21 days) → links to
  program detail / publish. Forms-missing item omitted (no source). Nothing when none.
- **Programs grid** — per program: sessions (period), attendance rate, publish state;
  `⋯` quick-action menu (links to that program's real actions). Forms column omitted.
- **Recent activity** — reuse `attendance/launchpad.recent_activity` (attendance +
  publish). Facilitator-added events omitted (User has no created timestamp).

**C. New launchpad queries** (`attendance/launchpad.py`), all verified, no PII:
- `org_stats(programs, start, end)` → dataclass: programs/students/sessions/
  attendance_rate/profiles_live.
- extend `program_cards` with period window + attendance-rate + stale-profile flag.

**D. Tests** (`tests/test_coordinator_home.py`, rewritten for the dashboard):
- dashboard requires auth; role scoping (coordinator org vs facilitator assigned).
- stat cards reflect real counts; Attendance-rate shows `—` with no records; Forms
  card shows `—` (honest empty); Profiles-live counts published snapshots.
- period selector changes the window (constructed week-vs-month case yields different
  sessions/students).
- needs-attention surfaces stale attendance + stale profile; empty when none.
- **no participant `display_name` anywhere on the dashboard** (PII probe).
- Tools menu: Live items are links; a Soon item is present but not an anchor.

### Explicitly NOT in slice 1.5
The attendance-capture screen (still slice 2), any Soon tool's real functionality,
search/⌘K, logout/login-landing, Reports/Network as top-level pages.
