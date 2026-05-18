# Handoff — Grants ingest, implementation session 1

**Date:** 2026-05-18
**Branch:** feat/grants-ingest-slice1
**Model:** Sonnet 4.6
**Next session:** Continue at commit 5 (Funder/Program tests), then commits 6–15.

---

## What shipped (commits on branch)

| # | Commit | Status |
|---|--------|--------|
| 0 | `chore: update CLAUDE.md Current phase` | done |
| 1 | `feat(grants_ingest): scaffold app` | done |
| 2 | `feat(grants_ingest): object store interface and FS implementation` | done |
| 3 | `feat(grants_ingest): RawRecord model + append-only enforcement` | done |
| 4 | `feat(grants_ingest): CorpusEvent model` | done |
| 5 | `wip: feat(grants_ingest): Funder, FunderAlias, Program, ProgramAlias models` | WIP — models + migration done, tests missing |

All commits pass pre-commit hooks (ruff, ruff-format, black). Django system check clean. 15 tests passing.

## What's queued (§8 of the plan)

Pick up at commit 5: write the CRUD/normalized-name tests for Funder/FunderAlias/Program/ProgramAlias, then convert the WIP commit to a clean feat commit.

Then continue in order:
- **6** — HistoricalGrant model + migration + idempotency test
- **7** — OpportunityInstance + CorpusSnapshot + IngestHealthSnapshot (schema only, no rows)
- **8** — BaseAdapter, HTTP utilities (httpx.MockTransport), retry + rate-limit tests
- **9** — materializer (`apply_events`, idempotency tests)
- **10** — entity resolver (normalization, EIN-wins-over-name, alias lookup)
- **11** — ProPublicaNPAdapter + synthetic JSON fixture + parse tests
- **12** — IRS990PFAdapter + synthetic XML fixture + parse tests
- **13** — management commands (ingest_run, materialize, snapshot_tag, unresolved_queue, ingest_health stub)
- **14** — DMV foundation seed list (EINs need human curation — see plan §8 note)
- **15** — usage README + next handoff

## One design note from this session

`CorpusEvent.content_sha` uses `blank=True, default=""` instead of `null=True` (plan showed nullable). Empty string == "no sha". Callers check `if event.content_sha:`. This avoids the ruff DJ001 / black formatter fight that null CharField causes. Not a schema deviation worth escalating — purely mechanical.

Added `[tool.ruff.lint.per-file-ignores]` for `grants_ingest/registry.py` to allow `null=True` on `Funder.ein` (unique nullable EIN requires true NULL, not empty string, because SQLite/Postgres treat multiple NULLs as distinct for unique constraints).

## Blockers / notes for next session

- `httpx` and `boto3` are installed in `.venv` but not in the IDE's selected interpreter — tests run fine with `.venv/bin/pytest`.
- Pre-commit hooks fight between ruff-format and black when inline `# noqa` comments force line wraps — the per-file-ignores pattern is the fix.
- Seed list (commit 14) needs human curation of ~30-50 DMV foundation EINs. Cross-check against recent 990-PFs per plan §8.
