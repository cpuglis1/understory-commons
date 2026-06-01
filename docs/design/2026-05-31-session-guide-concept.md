# Understory — the session guide (revised concept brief)

**Date:** 2026-06-02 · **Status:** core concept (post-review) · **Reference persona:** Matthew Ratz, Passion for Learning
**Design system:** locked coordinator look — mostly white, hairline borders, Inter UI, tabular figures, black primary buttons.

---

## The shape in one line

Set a program up once. Then each session is **two taps' worth of work** — open and take attendance, wrap up with a note. From that, two admin outputs fall out with no extra effort: a **live reporting view** for funders, and **month-end pay prep**.

```text
  SET UP ONCE              EACH SESSION                       FALLS OUT (no extra work)
  ───────────              ────────────                       ─────────────────────────
  program + roster   →   open → attendance → wrap → note  →   ├─ dashboard: attendance + status
  + defaults (time/pay)                                       └─ monthly: hours → pay-prep export
```

The facilitator only ever does the middle row. We deliberately refuse to build punch-clocks or granular dosage trackers — the system absorbs the messy reality of youth programs through smart defaults, not by shifting data-entry labor onto the facilitator.

---

## 0. Set up (one-time, per program — the coordinator)

When a program is created, the coordinator enters the baseline facts once:

* **Program basics:** name, site, and the **default facilitator**.
* **Roster:** the enrolled students' first names (PII-light). Pasted in a list.
* **The Pay Defaults:** the program's **default session length** (e.g., 90 min) and the facilitator's **rate**. Set once; never touched again by the facilitator.

---

## 1. In the session — two moments

### A. Open the session → attendance

```text
  ‹ Maplewood Film Club · Tue May 31
  ──────────────────────────────────
   WHO'S HERE?                ✓ active all here

     ● Maria     ● James
     ● Aisha     ● Devon
     ◯ Jayla     ● Noah

   ─ Inactive (missed 3+ sessions) ───────────
     ◯ Marcus

     + Add someone

     ● present   ◯ absent  ·  12 here · 2 out

  [        Wrap up session  →        ]
```

* **Binary Attendance:** Statuses are strictly **present / absent**. We do not track "15 minutes late" or "left early." If funders require down-to-the-minute dosage, Understory is the wrong tool.
* **The "Ghosting" Threshold (Handling Churn):** In real programs, kids stop showing up. If a student is marked absent 3 sessions in a row, they automatically drop below the "Inactive" divider. The **"all here"** button only applies to the active roster above the line. If Marcus shows up next week, tapping his name instantly bumps him back to the active list. *Zero roster maintenance required from the coordinator.*
* **"+ Add someone":** Drops in a new student (first name only) mid-year.

### B. Wrap up → a session note

The generic, universal progress signal. No taxonomies, no multi-step forms.

```text
  ‹ Wrap up · Maplewood Film · 12 here · 2 out
  ────────────────────────────────────────────
   HOW'D TODAY GO?

   What did you work on?                     🎤
   ┌──────────────────────────────────────────┐
   │ shot the final scene; kids ran their own │
   │ lighting                                 │
   └──────────────────────────────────────────┘

   Who ran today's session?
   [ Dana W. (Default) ⌄ ]

  [            Save & close  ✓             ]
```

* **The Free-Text Note:** Typed or dictated. This carries all the signal for the coordinator and funders. (We killed the "on track / behind" toggle — it trended toward a meaningless default).
* **Facilitator of Record:** Pay is decoupled from login identity. The system pre-fills the default facilitator, but if Marcus is covering for Dana and using her iPad, he changes this dropdown. This is the single source of truth for pay prep.

### C. The Midnight Rule (The unclosed session)

If a facilitator takes attendance but forgets to hit "Save & close," the session remains open to accommodate late arrivals. At **11:59 PM local time**, the server automatically closes any open sessions. It records the attendance as marked, logs an "Auto-closed" system note, and commits the default time for payroll. No data is lost in purgatory.

---

## 2. The reporting view (what the coordinator/funder sees)

A read of what the two taps captured. On the dashboard, each program now carries the line a coordinator currently has to reconstruct from memory:

```text
  Maplewood Film Club                          ⋯
  ──────────────────────────────────────────────
   Attendance   86%  · 12 sessions
   Recent       ✅✅❌✅ (last 4 sessions)
   Status       "shot the final scene"
   Last logged  Tue May 31 · by Dana
```

Instead of chasing down text messages, the coordinator points funders at this view. The single note plus the visual trend gives an immediate, trustworthy read on program health.

---

## 3. Pay prep — an honest byproduct

**How it works:** Three facts exist when a session closes: a session happened, the Facilitator of Record (from the wrap-up screen), and the default length (from setup).

Over the month, these sessions stack up into hours. At month-end, the coordinator opens a separate pay-prep view:

```text
  Facilitator pay · May 2026                export ⤓
  ──────────────────────────────────────────────────
   Facilitator    Sessions   Hrs    Rate   Amount
   Dana W.            8       12.0   $35    $420   [approve]
   Marcus T.          6        9.0   $35    $315   [approve]
   Priya S.           4        6.0   $40    $240   [✓ paid]
  ──────────────────────────────────────────────────
                                      Total  $975
```

* **Byproduct, not a punch-clock:** Hours = logged sessions × default length.
* **The Reconciler:** We don't ask facilitators to log if they ran 15 minutes over. If there was a half-day or a weather cancellation, the coordinator makes that **one-field adjustment here** before approving. We treat payroll as an estimate the coordinator reconciles, rather than a perfect math formula based on exhausted front-line workers tracking their minutes.
* **Export:** The coordinator clicks export and hands the clean CSV to Gusto, QuickBooks, or their bookkeeper. Understory stops at the math; it does not move money.

---

## How it all connects

```text
  ┌── SET UP (once) ──────────────────────────────────────────────┐
  │  program · roster · defaults (session length · rate)          │
  └───────────────────────────────────────────────────────────────┘
                     │
                     ▼
  ┌── EACH SESSION (the facilitator, on a phone) ─────────────────┐
  │  open → attendance  ·····  wrap up → note + facilitator       │
  └───────────────────────────────────────────────────────────────┘
                     │
        ┌────────────┴─────────────┐
        ▼                          ▼
  REPORTING VIEW             PAY PREP (monthly, coordinator)
  attendance + status        hours → amount → reconcile → export
  (dashboard / funder)       (hands off to a payment tool)
```

One habit in. Two finished outputs out.
