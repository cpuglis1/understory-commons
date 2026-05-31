# Design — Education-Director Dashboard (Coordinator command center)

**Date:** 2026-05-30
**Status:** Design proposal (not yet built). Supersedes the attendance-funnel
home from coordinator-surface slice 1.
**Surface:** Coordinator / education-director (the people who run the programs).

---

## Objective

Give the education director a **front-facing command center** — a single home
that answers *"how are my programs doing, and what needs me?"* at a glance, and
opens onto the **full suite of admin-automation tools** through one organized
menu.

The current home is a single-tool funnel ("log attendance"), so the product
reads like an attendance app. It is not one. It is an admin-automation platform
whose tools happen to **produce verified impact data as a byproduct**. The home
must communicate that: program-level statistics up top, a triage queue of what
needs attention, and a categorized **Tools** menu where attendance is one entry
among forms, payroll, family comms, progress, and funder/network work.

Two hard rules carry over and constrain every pixel below:

1. **Every number traces to a logged event** (the verification chain). A stat
   with no backing data shows an honest empty state — never a fabricated figure.
2. **PII-light.** Counts, rates, and statuses only. No participant identities
   beyond where the director already works with them.

---

## Who this is for

**Matthew Ratz, Executive/Education Director, Passion for Learning** (reference
persona). Runs several programs across multiple DC-area sites, 10–50 students
each, 1–3 paid staff plus volunteers. Time-poor, non-technical, lives in his
phone between sessions and at a laptop on Sunday nights. He does not want to
"use a dashboard" — he wants to know what's on fire, knock out the week's admin,
and have something credible to show a funder. The dashboard earns its place only
if it routes him into real work and reflects work already done.

---

## Design principles

1. **Director altitude, not tool altitude.** The home reports on the *whole
   organization*. Tool-specific screens live one level down, reached from the
   Tools menu or a program row — never the home's only job.
2. **Verified, never vanity.** Stats are operational rollups derived from logged
   events (sessions, attendance, forms, publishes), not predictive "insights."
   This keeps us inside V1 scope (no analytics product) while still feeling like
   a real dashboard.
3. **One platform, many tools.** A categorized Tools menu makes the breadth
   legible. Seeing "Forms," "Payroll," "Family comms," "Funder & network" next to
   "Attendance" is what stops this from looking like an attendance app.
4. **Honest emptiness.** Tools that aren't built yet, and stats with no data yet,
   say so plainly (a quiet "Coming" pill, a "—" with a "start here" link). We
   never mock data to look fuller.
5. **Calm and tech-forward.** Generous whitespace, one accent color, big tabular
   numbers, hairline borders, soft depth. Data-dense without clutter.
   Mobile-first, excellent on desktop. HTMX for interactions — no SPA.

---

## Global navigation

A sticky top bar. The **Tools ▾** entry is a mega-menu — this is the "dropdown
tab with categories and sub-tools" that makes the platform feel whole.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│  ◬ UNDERSTORY   Dashboard   Programs   Tools ▾   Reports   Network    ⌘K   M.R ▾ │
└───────────────────────────────────────────────────────────────────────────────┘
```

- **Dashboard** — the command center (this doc's main page).
- **Programs** — list/grid of all programs; drill into one.
- **Tools ▾** — the categorized mega-menu (below).
- **Reports** — CSV / PDF exports for funders and grant reporting.
- **Network** — how the org appears to donors (public profiles, grants surfaced).
- **⌘K** — command palette: jump to any program or tool by typing.
- **M.R ▾** — account: name, role badge, org, sign out.

### The Tools mega-menu

Opening **Tools ▾** drops a multi-column menu. Each column is a category; each
row is a sub-tool with a status pill (`Live` · `Beta` · `Coming`). Everything is
reachable — nothing is hidden — but the pill sets honest expectations.

```
┌──────────────────────── TOOLS ──────────────────────────────────────────────────────┐
│  ATTENDANCE &           FORMS &              STAFF &               FAMILY             │
│  PARTICIPATION          PERMISSIONS          PAYROLL               COMMUNICATION      │
│  • Log attendance  Live • Permission forms  ○ • Timesheets       ○ • Weekly update   ○│
│  • Roster & history ○   • Media / photo     ○ • Monthly payroll  ○ • Announcement    ○│
│  • Participation        consent               prep                 draft              │
│    trends          ○    • Form status by    ○ • Facilitators &  Live• (generation —   │
│                           program               invites              copy to your     │
│                                                                      own channel)     │
│                                                                                       │
│  PROGRAM PROGRESS       FUNDER & NETWORK                                              │
│  • Project milestones ○ • Publish public profile          Live                       │
│  • Photo & testimonial  • Public program page             Live                       │
│    intake             ○ • Grant-report sections (from data) ○                         │
│  • Satisfaction       ○ • Find grants (DMV youth-ed)      Beta                        │
│    survey               • Export CSV / PDF                ○                           │
└───────────────────────────────────────────────────────────────────────────────────────┘
  Live = working today   Beta = backend exists, UI thin   ○ Coming = on the roadmap
```

This taxonomy is a direct mapping of the admin-automation priority list and the
existing surfaces. It is the product's table of contents.

---

## The dashboard page

Four stacked zones. On desktop they form a 12-column grid; on mobile they stack.

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  Good evening, Matthew.                              [ This month  ▾ ]          ║   ← context + period selector
║  Passion for Learning · 3 programs · 2 sites                                    ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ║
║  │   3      │ │   38     │ │   24     │ │   86%    │ │   4      │ │   2      │ ║   ← org stat cards (verified)
║  │ Active   │ │ Students │ │ Sessions │ │ Attend.  │ │ Forms    │ │ Profiles │ ║
║  │ programs │ │ reached ✓│ │ held   ✓ │ │ rate   ✓ │ │ outstand.│ │ live   ✓ │ ║
║  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║  NEEDS ATTENTION                                                                ║
║  ▸ Thursday Coding Club — no attendance logged in 7 days        → Log           ║   ← triage queue, each links to the tool
║  ▸ Reading Stars — 4 permission forms missing                   → Forms         ║
║  ▸ Reading Stars — public profile 21 days stale                 → Publish       ║
╠══════════════════════════════════════════════╦════════════════════════════════╣
║  PROGRAMS                                      ║  RECENT ACTIVITY               ║
║  ┌───────────────────────────────────────┐    ║  ● Profile published — Reading ║
║  │ Reading Stars   Blair HS              ⋯│    ║    Stars · M.R · 2h ago        ║   ← cross-program event
║  │ 12 sess · 86% · forms 8/12 · live v1   │    ║  ● Attendance — Reading Stars  ║      stream (verified)
║  ├───────────────────────────────────────┤    ║    May 26 · 10 students · 2h   ║
║  │ Coding Club     Silver Spring        ⋯│    ║  ● Facilitator added — Fran    ║
║  │ 0 sess · — · forms — · not published   │    ║    · M.R · yesterday           ║
║  ├───────────────────────────────────────┤    ║  ● Attendance — Reading Stars  ║
║  │ Math Lab        Blair HS             ⋯│    ║    May 21 · 9 students         ║
║  └───────────────────────────────────────┘    ║                                ║
║   ⋯ = per-program quick actions (any tool)     ║  View all activity →           ║
╚════════════════════════════════════════════════╩════════════════════════════════╝
                            ✓ = number derived from logged events; the rest are statuses
```

### Zone 1 — Context + period selector
Greeting, org name, program/site count, and a period selector (This week /
This month / This term). The selector reframes every stat below. No vanity copy.

### Zone 2 — Org stat cards (verified rollups)
Six cards, big tabular numbers, label, and a provenance tick (`✓`) on the ones
derived from the event log. Cards:

| Card | Source | Notes |
|---|---|---|
| Active programs | `programs_visible_to` | not-archived count |
| Students reached ✓ | `attendance.queries.students_attending` | distinct present/late, this period |
| Sessions held ✓ | `attendance.queries.sessions_held` | this period |
| Attendance rate ✓ | derived (present ÷ expected) | shown only when sessions > 0 |
| Forms outstanding | forms tool (when built) | `—` + "set up forms" until then |
| Profiles live ✓ | published `ProfileSnapshot`s | links to Network |

A card with no data shows `—` and a one-tap "start logging" link. Never a zero
dressed up as an achievement, never a fabricated figure.

### Zone 3 — Needs attention (the triage queue)
The director's to-do, assembled from real signals across tools: stale attendance,
missing permission forms, unsubmitted timesheets, stale public profiles. Each row
links straight to the tool that resolves it. This is the home's action engine —
it replaces "one big Log Attendance button" with "here's everything that needs
you, ranked."

### Zone 4a — Programs
A compact card/row per program: site, sessions this period, attendance rate,
forms status, publish state, and a `⋯` quick-action menu that can launch *any*
tool scoped to that program. This is the "how is each program doing" view.

### Zone 4b — Recent activity
A cross-program, cross-tool event stream — attendance logged, profile published,
facilitator added, form collected, timesheet submitted — each with actor +
timestamp. Verified events only; counts not names. "View all activity" opens the
full log.

---

## Visual design language

**Decided (Chris, 2026-05-30):** the slickest tech-startup register — a **top
bar** nav, **mostly white with black text**, **a cursive/script wordmark**, real
classy. In short: the Vercel/Linear monochrome discipline (pure white, near-black
ink, black buttons, hairline borders, Inter) warmed by an elegant script logo.
Near-monochrome chrome; color appears only to carry meaning (status, attention).

| Token | Value | Use |
|---|---|---|
| `surface` | `#FFFFFF` (pure white), optional `#FCFCFC` panels | app background |
| `card` | `#FFFFFF`, border `#EAEAEA`, radius `12px`, shadow `0 1px 2px rgba(0,0,0,.04)` | every panel |
| `ink` / `muted` | `#0A0A0A` / `#6B7280` | text / secondary text |
| `line` | `#EAEAEA` | hairline borders, dividers |
| `primary` | `#0A0A0A` bg, white text | primary buttons & CTAs (classy mono) |
| status pills | green `Live` · amber `Attention` · slate `Coming` · neutral `Published` | semantic only — chrome stays mono |
| `tick` | `#16A34A` | the small verified `✓` on derived stats — the one green note |

- **Wordmark:** a script face — **Pinyon Script** (Google Fonts) for "Understory
  Commons," ~1.6rem, black. Classy + "kinda cursive," legible at logo size.
  Swappable in one line (Tangerine / Parisienne / Cormorant-italic are alternates).
- **UI type:** Inter (system-ui fallback) for everything else. Stat figures
  `font-variant-numeric: tabular-nums`, weight 700–800, ~2.25rem. Section labels
  0.75rem, muted, uppercase, letter-spaced. The script never appears in UI chrome
  — only the logo. The script/grotesque contrast is the whole "classy" move.
- **Grid & spacing:** 8px base. Centered content column ~1080px. Cards breathe
  (20–24px padding). Lots of white.
- **Depth:** hairline borders + one whisper-soft shadow. No heavy shadows, no
  gradients. Black is reserved for ink and primary actions.
- **Motion:** HTMX swaps with a 120ms fade; the Tools mega-menu and period
  selector are the only flourishes. Nothing bounces.
- **Iconography:** one thin line-icon set (Lucide), 1.5px stroke, monochrome,
  used sparingly — Tools categories, the `⋯` menu, stat cards.

---

## Component inventory (build order within the shell)

1. **App shell** — sticky top bar, Tools mega-menu, account menu, `⌘K` palette
   stub, content slot. (Extends the slice-1 shell.)
2. **StatCard** — number, label, provenance tick, empty state.
3. **AttentionItem** — icon, message, deep link to resolving tool.
4. **ProgramRow** — facts + `⋯` quick-action menu.
5. **ActivityItem** — already exists (`attendance/launchpad.py`); generalize its
   source to any tool's events once a second tool emits them (per the repo rule:
   no shared abstraction until the second real case).
6. **StatusPill**, **PeriodSelector**, **EmptyState**.

---

## Data, invariants, and honesty

- **Verification chain.** Stat cards and the activity stream read only
  `attendance.queries`, published `ProfileSnapshot`s, and (as they ship) each
  tool's own logged events. No new metric source; no number the director could
  edit by hand.
- **PII boundary.** The home shows program-level counts, rates, statuses, and
  *staff* actors (the director's own people). No participant `display_name`
  reaches the home — consistent with slice 1's PII test.
- **Append-only.** The activity stream is a read over the event log; it never
  mutates.
- **Scope honesty.** CLAUDE.md keeps "real-time analytics / insights" out of V1.
  This design stays on the right side of that line by showing **verified
  operational rollups** (byproducts of admin work), not predictive analytics.
  The dashboard *layout* is the target; cells fill with real data only as the
  tool behind them ships. Until then: honest empties.

---

## What's real today vs. target

| Zone / tool | Today | To build |
|---|---|---|
| App shell + nav | slice-1 shell (top bar, role) | Tools mega-menu, account menu, ⌘K |
| Sessions / Students / Attendance-rate cards | queries exist | card UI + period selector |
| Profiles-live card + Network | publish/preview/public page (step 4) | surface on dashboard |
| Facilitators & invites | working (`accounts`) | put in Tools menu |
| Find grants | grants_ingest backend (7 adapters) | thin UI = "Beta" |
| Attendance capture | slice-1 stub | slice 2 (the real screen) |
| Forms, Payroll, Family comms, Progress | not started | future slices, `Coming` pills |

So the dashboard is *not* speculative scaffolding: roughly half the cells have
real data or working tools today. It reframes what already exists as a platform
and leaves honest placeholders for the rest.

---

## Fieldwork test

After this ships, Matthew opens the app on Sunday night and — without hunting —
sees that Coding Club hasn't met, Reading Stars is missing four permission forms,
and its funder profile is going stale. He clears the forms item in two taps, logs
Saturday's attendance from the same screen's program row, and re-publishes the
profile before closing the laptop. He never "visited a dashboard"; he triaged his
week. The attendance tool did its job — as *one* of the things the platform did
for him, which is exactly the impression the redesign exists to create.

---

## Decisions & open questions

**Resolved (Chris, 2026-05-30):**
- **Nav shape → top bar** with the Tools ▾ mega-menu (slickest startup version).
- **Aesthetic → mostly white, black text, script wordmark, classy** (mono chrome;
  Vercel/Linear discipline + Pinyon Script logo). See Visual design language.

**Still open:**
1. **Stat period default:** This month (matches the publish window) vs. This week
   (matches Matthew's logging rhythm). *Leaning: This month.*
2. **Network tab now or later:** surface the donor-facing view in V1 nav now, or
   keep the coordinator surface clean until profiles are richer? *Leaning: keep a
   Network tab — it's a differentiator and the public pages already exist.*
3. **Wordmark font:** Pinyon Script (drawn) vs. a slightly less formal script
   (Parisienne) vs. an editorial italic serif (Cormorant). Trivial to swap.

> Next step if approved: I implement the **app shell + Tools mega-menu + the six
> stat cards and needs-attention queue against real data**, leaving `Coming`
> tools as honest stubs — then we re-run the fieldwork test against the live page.
