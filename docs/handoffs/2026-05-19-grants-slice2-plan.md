# Handoff — Grants ingest slice 2 plan (Tier-A `pnd_rfp` + `grants_gov`)

**Date:** 2026-05-19
**Model:** Opus 4.7 (planning session)
**Branch:** `feat/grants-ingest-slice1` (planning artifacts only; no code)
**Plan:** [`docs/plans/2026-05-19-grants-ingest-slice2-tierA.md`](../plans/2026-05-19-grants-ingest-slice2-tierA.md)
**Predecessor:** [slice-1 completion note](2026-05-18-grants-slice1-complete.md)

---

## What the plan decided

1. **Two new Tier-A adapters this slice, no others.** `pnd_rfp` (Candid RSS + per-item secondary fetch of the funder's own page) and `grants_gov` (daily XML extract, with the linked Description PDF fetched as a separate RawRecord but **not parsed**).

2. **First slice that creates `OpportunityInstance` rows.** Slice 1 scaffolded the model but produced 0 rows. Slice 2 wires up the materializer and produces the first opportunities.

3. **`OpportunityInstance` gets four new fields** in one migration: `notes` (JSON), `source_id` (indexed), `external_id` (indexed), `funder_name_raw`. Plus `unique_together = [("source_id", "external_id")]` for materializer dedup. The full `EligibilityStruct` is **explicitly deferred** to slice 3+ — slice 2 stores raw codes only in `notes`. This was the load-bearing scope call.

4. **Three new `CorpusEventType` values:** `OPPORTUNITY_SEEN`, `OPPORTUNITY_UPDATED`, `OPPORTUNITY_FILTERED`. No removals, no renames — additive only, backward compatible with slice-1 data.

5. **Pre-filtering happens at parse time, before any `OpportunityInstance` exists.** `pnd_rfp` filters on geographic scope (national/DC/MD/VA/DMV). `grants_gov` filters on the three-rule combination (eligible-applicant code ∈ {25, 12}, CFDA prefix ∈ {84., 93.5, 16.} OR category code ∈ {E, ED, HL}, AwardFloor < 250K or absent). Both adapters log a `OPPORTUNITY_FILTERED` event for records that fail — raw bytes are still stored, but no opportunity row is created.

6. **Description PDFs from grants.gov are stored, not parsed.** Slice 2 fetches the linked PDF as its own `RawRecord` with a 50MB cap, linked via the M2M `source_records` on `OpportunityInstance`. Parsing waits for Component 2.

7. **Funder auto-create policy is asymmetric.** On a resolver miss, `grants_gov` opportunities auto-create a `Funder` with `funder_type=GOVT_FEDERAL` (federal agencies are a closed set, ~30 names). `pnd_rfp` opportunities **do not** — they go to the manual-review queue. Auto-creation lives in the management command, not in `resolution.py` (which stays a pure function).

8. **Two-pass adapter run for `pnd_rfp`** (RSS first, then per-item source-page fetches) is handled by overriding `run()` inside the adapter for now, not by extending `BaseAdapter`. Lift to base class if/when a second use case appears (likely in slice 4's `cf_*` work).

9. **Management command surface stays compact.** `ingest_run` gets two new sources in its `choices`. `resolve_entities` gets a `--target` flag (opportunities | historical_grants | all). No new commands.

10. **8 commits sized for 4-7 days of Sonnet implementation work**, mirroring slice-1's cadence. Dependency map in plan §10: PND and grants.gov tracks split after the materializer commit (#2) and can run in parallel implementation sessions.

---

## Key open questions for you before coding starts

These are the real branches in the design space. Each has a recommended default but warrants your decision before Sonnet picks one.

### Q1. Grants.gov path — XML-only or dual-path with REST API?
- **Plan recommends:** XML-only for slice 2. Simpler, no auth risk, well-behaved.
- **Tradeoff if XML-only:** cannot replay historical closed opportunities from grants.gov bulk data alone.
- **Cost of dual-path now:** +1 commit, +1 open question (auth posture of api.grants.gov v2 in 2026).
- **Default if no input:** XML-only.

### Q2. Auto-create `Funder` rows from `grants_gov` resolver misses?
- **Plan recommends:** yes for `grants_gov` (closed set), no for `pnd_rfp` (long tail).
- **Alternative:** never auto-create; all unresolved opportunities sit in the manual-review queue and you triage by hand.
- **Cost of alternative:** ~30 hand-resolutions on first ingest run.
- **Default if no input:** asymmetric policy in plan §3.5.

### Q3. EligibilityStruct timing — confirm deferral
- **Plan recommends:** defer to slice 3+ (or its own focused slice between 2 and 3). Slice 2 stores raw codes in `notes` only.
- **Reason to defer:** producing a real EligibilityStruct from grants.gov XML requires a lookup table for EligibleApplicants codes and a normalized geo schema — both tractable but each their own design. A more representative corpus (grants.gov + `cf_*`) makes for a better v1 schema.
- **Cost of building now:** ~2 extra commits, risks a v1 schema that gets reshaped once `cf_*` data lands.
- **Default if no input:** defer per plan §3.2.

### Q4. Schema lock-in for `OpportunityInstance` — accept the four new fields now?
- **Plan recommends:** lock the four new fields (`notes`, `source_id`, `external_id`, `funder_name_raw`) before any rows land. Let `notes` JSON keys grow per source.
- **Alternative:** grow the schema per source as slices 3+ add `cf_*` etc.
- **Default if no input:** plan §3.1 as written.

### Q5 (minor). PND RSS URL verification
The plan treats `https://philanthropynewsdigest.org/rfps/rss` as provisional. Candid has moved feeds before. Implementation must verify on day 1 and update the plan if it differs. Worth confirming you're OK with that posture rather than wanting URL verification up-front before this plan is approved.

### Q6 (minor). `RAW_OBJECT_STORE_FS_PATH` env default
Carried from slice-1 handoff. The env var has no Django default and must be set manually. Suggest adding a `.env.dev.example` and/or a Django settings fallback (`/tmp/uc-corpus`) before slice 2 implementation starts so the first Sonnet session doesn't trip on it.

---

## Recommended next action

1. **Answer the four major open questions (Q1–Q4) above.** Q5 and Q6 can wait or be handled inline during implementation.

2. **Decide whether to ship the env-var fallback (Q6) as a prerequisite chore commit** before slice 2 implementation begins. ~15 min of work; removes a recurring friction.

3. **Then `/clear` and open a fresh Sonnet implementation session** with this handoff + the plan as the initial context. The plan is the contract; implementation works against it commit-by-commit per §7. If implementation reveals the plan is wrong, stop and update the plan rather than papering over it (per CLAUDE.md workflow conventions).

4. **The two adapter tracks (PND vs grants.gov) can be split** across two implementation sessions if context budget gets tight. Both depend on commits #1 and #2 (the migration + materializer extension), then diverge. Plan §10 shows the dependency graph.

5. **The deferred IRS 990-PF ObjectId unblock** (from slice-1 known limitations) is **not on slice 2's path**. Slice 2 ships without `HistoricalGrant` growing. That work is tied to Component 6 / outcome ranking and waits.

---

## What this handoff did not do

- No code written. No migrations generated. No tests added. Pure planning artifact.
- No dependency-versioning decisions (e.g., do we add `feedparser` or stick with stdlib `xml.etree.ElementTree` for RSS? — plan §1.2 leaves the call to the implementer with a default of stdlib).
- No verification of the exact PND RSS URL or grants.gov daily-extract URL. Treated as provisional in the plan; first-day implementation step is to confirm both URLs against a live fetch.
- No live data ingested. The slice-2 live verification run mirrors slice-1's bug-bash: it happens at commit #8, not before.
