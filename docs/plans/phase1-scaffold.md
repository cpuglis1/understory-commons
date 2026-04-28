# Phase 1 Scaffold Plan — Understory Commons

Working document. Implementation-ready. Coordinator surface only. No donor surface, no email/SMS delivery, no exports, no styling beyond HTMX defaults.

---

## 1. App structure

**Django project name:** `understory_commons`

**Apps:**

- `core` — `Organization`, `Program`, `Session`, base mixins, shared template tags, home/dashboard views.
- `accounts` — Custom `User` model, `Role` (coordinator | facilitator), `MagicLinkToken` model and views, account-creation flow.
- `attendance` — `Participant`, `AttendanceRecord`, attendance capture views (free-text + manual fallback), confirmation/disambiguation flow, merge-participants admin action.
- `commons` — Non-Django Python package (importable, not a Django app). Holds `commons/ai/client.py` and prompt templates. Lives at the repo root alongside `manage.py`, registered on `PYTHONPATH` via `src/` layout or top-level placement.

**Directory layout:**

```
understory-commons/
  manage.py
  pyproject.toml
  ruff.toml                  # or [tool.ruff] in pyproject
  .pre-commit-config.yaml
  .python-version            # 3.12
  railway.toml
  Procfile
  .env.example
  understory_commons/
    __init__.py
    settings/
      __init__.py
      base.py
      dev.py
      prod.py
    urls.py
    wsgi.py
    asgi.py
  core/
    models.py
    views.py
    urls.py
    admin.py
    migrations/
    templates/core/
  accounts/
    models.py
    views.py
    urls.py
    admin.py
    backends.py              # magic-link auth backend
    migrations/
    templates/accounts/
  attendance/
    models.py
    views.py
    urls.py
    admin.py                 # merge-participants action lives here
    forms.py
    migrations/
    templates/attendance/
  commons/
    __init__.py
    ai/
      __init__.py
      client.py
      prompts/
        attendance_parse.py
  templates/
    base.html
  static/                    # empty in V1; HTMX via CDN in base.html
  tests/
    conftest.py
    test_models.py
    test_attendance_flow.py
    test_ai_client.py
    test_auth.py
  docs/
    plans/
      phase1-scaffold.md
```

---

## 2. Data model

All models live in their app's `models.py`. All models inherit a `TimestampedModel` abstract base (in `core/models.py`) with `created_at` and `updated_at`. Append-only models override `save()` to forbid updates after creation; see flags below.

### `core.Organization`
- `id`: UUID primary key
- `name`: `CharField(max_length=200)`
- `created_at`, `updated_at`: from base

One per CBO. No multi-tenant routing in V1; org scoping is enforced in querysets.

### `accounts.User` (custom, `AUTH_USER_MODEL`)
- `id`: UUID primary key
- `email`: `EmailField(unique=True)` — login identifier
- `display_name`: `CharField(max_length=200)`
- `organization`: `ForeignKey(Organization, on_delete=PROTECT, related_name="users")`
- `role`: `CharField(choices=[("coordinator","coordinator"),("facilitator","facilitator")])`
- `is_active`: `BooleanField(default=True)`
- `is_staff`: `BooleanField(default=False)` — Django admin gate; coordinators may be granted but not required
- `last_login`: standard
- No `password` usage in V1. `set_unusable_password()` on creation. Authentication is magic-link only.

`USERNAME_FIELD = "email"`, `REQUIRED_FIELDS = ["display_name"]`. Use a custom `UserManager`.

### `accounts.MagicLinkToken` *(append-only)*
- `id`: UUID primary key
- `user`: `ForeignKey(User, on_delete=CASCADE, related_name="magic_links")`
- `token`: `CharField(max_length=64, unique=True, db_index=True)` — `secrets.token_urlsafe(48)`
- `created_at`: auto
- `expires_at`: `DateTimeField` — `created_at + 7 days`
- `consumed_at`: `DateTimeField(null=True, blank=True)` — set once on use; the only mutable field
- `created_by`: `ForeignKey(User, on_delete=PROTECT, related_name="+")` — coordinator who minted the link

Append-only except `consumed_at`. **Verification chain:** the `created_by` and `consumed_at` columns are auditable evidence that an account access occurred.

### `core.Program`
- `id`: UUID primary key
- `organization`: `ForeignKey(Organization, on_delete=PROTECT, related_name="programs")`
- `name`: `CharField(max_length=200)`
- `site_label`: `CharField(max_length=200, blank=True)` — free-text location string, no Site model
- `coordinator`: `ForeignKey(User, on_delete=PROTECT, related_name="coordinated_programs", limit_choices_to={"role":"coordinator"})`
- `facilitators`: `ManyToManyField(User, related_name="facilitated_programs", limit_choices_to={"role":"facilitator"}, blank=True)`
- `is_archived`: `BooleanField(default=False)`

Constraint: `coordinator.organization == organization` enforced in `clean()`.

### `core.Session`
- `id`: UUID primary key
- `program`: `ForeignKey(Program, on_delete=PROTECT, related_name="sessions")`
- `scheduled_date`: `DateField`
- `notes`: `TextField(blank=True)` — facilitator free-text post-session notes (optional)
- `created_at`, `updated_at`

Unique together: `(program, scheduled_date)`. Sessions are mutable (date can shift, notes can be edited) — they are not the verification artifact; AttendanceRecords are.

### `attendance.Participant`
- `id`: UUID primary key
- `organization`: `ForeignKey(Organization, on_delete=PROTECT, related_name="participants")`
- `display_name`: `CharField(max_length=200)` — **the only PII field**
- `merged_into`: `ForeignKey("self", null=True, blank=True, on_delete=PROTECT, related_name="merged_from")` — set when this participant has been merged into another; queries should filter `merged_into__isnull=True` for active roster
- `created_at`, `updated_at`

**PII boundary:** no first/last split, no parent contact, no DOB, no address, no notes. Any future addition crosses the PII boundary and must be escalated.

### `attendance.AttendanceRecord` *(append-only)*
- `id`: UUID primary key
- `session`: `ForeignKey(Session, on_delete=PROTECT, related_name="attendance_records")`
- `participant`: `ForeignKey(Participant, on_delete=PROTECT, related_name="attendance_records")`
- `status`: `CharField(choices=[("present","present"),("late","late"),("absent","absent"),("excused","excused")])`
- `recorded_by`: `ForeignKey(User, on_delete=PROTECT, related_name="recorded_attendance")`
- `recorded_at`: `DateTimeField(auto_now_add=True)`
- `source`: `CharField(choices=[("llm_parse","llm_parse"),("manual_form","manual_form")])`
- `raw_input`: `TextField(blank=True)` — the original facilitator free-text for `llm_parse` rows; empty for `manual_form`
- `llm_request_id`: `CharField(max_length=128, blank=True)` — Anthropic response id, when applicable

**Append-only.** Override `save()` to raise on update (only `pk is None` path allowed). No `updated_at`. No status corrections — corrections are written as a new record; reporting takes the latest record per `(session, participant)` by `recorded_at`.

**Verification chain FKs:** `session`, `participant`, `recorded_by` all `PROTECT`. `recorded_at` and `recorded_by` are the non-repudiable timestamp + actor.

### Idempotency
- Magic-link consumption: `consumed_at` set in a `SELECT ... FOR UPDATE` transaction; second use returns the same authenticated session without minting duplicate records.
- Attendance submission: confirmation form posts an `idempotency_key` (UUID minted on the parse-result page). View checks for existing AttendanceRecords created with that key in the last 10 minutes; if present, redirect to success without re-writing. Store the key in a `submission_idempotency_key: CharField(max_length=64, blank=True, db_index=True)` column on `AttendanceRecord` (or a small dedicated `AttendanceSubmission` row — pick the column).

---

## 3. Auth implementation

**Decision: roll a minimal custom magic-link.** `django-sesame` is competent but its assumptions (URL-embedded signed tokens, automatic email integration patterns) add surface area we do not need given (a) tokens are copied by hand, not emailed, (b) we want explicit `MagicLinkToken` rows for the verification chain, (c) no password fallback. ~80 lines of custom code is less than understanding sesame's settings matrix.

### Token mint
- `accounts.services.mint_magic_link(user, created_by) -> MagicLinkToken`
- `token = secrets.token_urlsafe(48)`
- `expires_at = now() + timedelta(days=7)`
- Returns the row; caller composes the URL: `f"{SITE_URL}{reverse('accounts:magic_login', args=[token])}"`

### Coordinator creates a facilitator
1. Coordinator visits `/accounts/facilitators/new/`
2. Form fields: `display_name`, `email`, `programs` (multi-select of programs they coordinate)
3. On submit: create `User(role="facilitator", organization=coordinator.organization)`, set unusable password, assign programs (M2M), mint a `MagicLinkToken`, render a page that displays the full URL with a copy button. **The system never sends the link.** The coordinator copies it and delivers it via their own channel.
4. Coordinator can re-mint a fresh token at any time from the facilitator detail page (e.g., `/accounts/facilitators/<id>/`). Old unconsumed tokens remain valid until expiry; this is acceptable for V1.

### Token validation (`accounts/views.py::magic_login`)
- URL: `/auth/magic/<token>/`
- In a transaction: `MagicLinkToken.objects.select_for_update().get(token=token)`
- Reject if `expires_at < now()` or `consumed_at is not None`
- Set `consumed_at = now()`, save
- `django.contrib.auth.login(request, token.user)` (custom backend below)
- Redirect to `/` (dashboard)

### Auth backend (`accounts/backends.py`)
Custom `ModelBackend` subclass that **does not authenticate by password**. `authenticate()` returns `None` for any password attempt. Login is performed by directly calling `login(request, user)` after token validation; the backend exists only so `request.user` resolution works.

Set `AUTHENTICATION_BACKENDS = ["accounts.backends.MagicLinkBackend"]`.

### Role separation
**Use Django Groups, not custom permission classes.** On user creation, add to `Coordinators` or `Facilitators` group. Groups are seeded in a data migration in `accounts/migrations/`.

Permission checks via two view decorators in `accounts/decorators.py`:
- `@coordinator_required` — 403 if `request.user.role != "coordinator"`
- `@facilitator_or_coordinator_required` — 403 if neither

Program-scoping helper in `core/queries.py`:
- `programs_visible_to(user) -> QuerySet[Program]`
  - coordinator: `Program.objects.filter(organization=user.organization)`
  - facilitator: `user.facilitated_programs.all()`
- Every program-scoped view calls this. **No view queries `Program.objects` directly.**

---

## 4. Attendance capture flow

### URL routes (`attendance/urls.py`, mounted at `/attendance/`)

| Path | Name | Method | Purpose |
|---|---|---|---|
| `/sessions/<session_id>/` | `session_detail` | GET | Session landing page; shows existing records and "Take attendance" button |
| `/sessions/<session_id>/capture/` | `capture` | GET | Free-text input form (HTMX-targeted) |
| `/sessions/<session_id>/parse/` | `parse` | POST | Calls LLM, returns confirmation partial with parsed rows + disambiguation |
| `/sessions/<session_id>/confirm/` | `confirm` | POST | Writes AttendanceRecords, returns success partial |
| `/sessions/<session_id>/manual/` | `manual` | GET, POST | Manual fallback form (checkbox table over existing roster) |

### View flow
1. **`capture` (GET)** — renders `attendance/capture.html`. Form posts to `parse` via `hx-post`.
2. **`parse` (POST)** — receives `{raw_text}`. Calls `commons.ai.client.parse_attendance(raw_text, roster=...)`. Roster is `Participant.objects.filter(organization=session.program.organization, merged_into__isnull=True).values_list("id","display_name")`. Returns HTMX partial `_confirm.html` with one row per parsed entry plus an `idempotency_key` hidden field. Each row carries: `parsed_name`, `status`, `match_state` (`new` | `existing:<participant_id>` | `ambiguous:<id>,<id>,...`), and the original raw substring.
3. **Confirmation UI (`_confirm.html`)** — for each parsed row:
   - `match_state="new"` → radio: "Create new participant 'Markus'" (default) | "Same as: <dropdown of existing participants>"
   - `match_state="existing:<id>"` → shows matched name, edit link to override
   - `match_state="ambiguous:..."` → radio between candidates plus "new participant" option
   - Status dropdown editable per row
   - Submit posts to `confirm`
4. **`confirm` (POST)** — for each row:
   - Resolve participant: create new `Participant` if directed, else use selected existing
   - Create `AttendanceRecord` with `source="llm_parse"`, `recorded_by=request.user`, `raw_input=raw_text`, `submission_idempotency_key=<key>`, `llm_request_id=<id>`
   - All in one `transaction.atomic()`. Idempotency: short-circuit if any record already exists with this key.
   - Returns `_success.html` with summary.
5. **`manual` (GET/POST)** — `GET` renders checkbox table over existing org roster (excluding `merged_into__isnull=False`). `POST` writes records with `source="manual_form"`. No LLM. Disabled with helper text if roster is empty.

### Templates
- `attendance/templates/attendance/capture.html` — full page, extends `base.html`
- `attendance/templates/attendance/_confirm.html` — HTMX partial
- `attendance/templates/attendance/_success.html` — HTMX partial
- `attendance/templates/attendance/manual.html` — full page

### HTMX patterns
- `hx-post` to `parse` with `hx-target="#capture-region"` and `hx-swap="outerHTML"`
- HTMX spinner via `hx-indicator` is sufficient; no async queue.

---

## 5. AI module design (`commons/ai/client.py`)

### Public interface

```python
from typing import Literal, TypedDict

Status = Literal["present", "late", "absent", "excused"]

class ParsedRow(TypedDict):
    parsed_name: str           # exactly as facilitator wrote it, trimmed
    status: Status
    match_participant_id: str | None  # set if model is confident
    candidate_ids: list[str]   # populated when ambiguous (>=2)
    raw_substring: str         # the chunk of input this row came from

class ParseResult(TypedDict):
    rows: list[ParsedRow]
    request_id: str            # Anthropic response id
    model: str

def parse_attendance(
    raw_text: str,
    roster: list[tuple[str, str]],   # [(participant_id, display_name), ...]
) -> ParseResult: ...
```

Internally:
- One module-level `Anthropic` client, instantiated lazily with `ANTHROPIC_API_KEY` from settings.
- Model: `claude-sonnet-4-6` (per spec, all V1 calls).
- **No view ever imports `anthropic` directly.** Enforced by a ruff custom rule or a simple test that greps the codebase.

### Prompt design (`commons/ai/prompts/attendance_parse.py`)

System prompt (literal, do not paraphrase in implementation without re-reviewing):

```
You are parsing a youth program facilitator's free-text attendance note into structured records.

Output strict JSON matching this schema:
{
  "rows": [
    {
      "parsed_name": "<the name as written, trimmed>",
      "status": "present" | "late" | "absent" | "excused",
      "match_participant_id": "<uuid string or null>",
      "candidate_ids": ["<uuid>", ...],
      "raw_substring": "<the substring of input this row came from>"
    }
  ]
}

Rules:
- Default status is "present" unless the text indicates otherwise.
  - "late", "tardy", "came late" -> "late"
  - "absent", "out", "out sick", "didn't come" -> "absent"
  - "excused", "excused absence" -> "excused"
- Match each parsed name against the provided roster. The roster is: {roster_json}
- If a parsed name matches exactly one roster entry (case-insensitive, ignoring punctuation), set match_participant_id to that id and leave candidate_ids empty.
- If a parsed name plausibly matches 2+ roster entries (e.g., "Marcus" could be "Marcus T." or "Marcus B."), set match_participant_id to null and list the candidate ids.
- If a parsed name has no plausible roster match, set both fields to null/empty.
- Do not invent names. Do not split a single mention into two rows.
- Return only the JSON object, no prose, no markdown fences.
```

User message: the raw facilitator text, verbatim.

Use Anthropic's tool-use / structured output if Sonnet 4.6 supports it cleanly; otherwise parse JSON from text response with a strict `json.loads` and a single retry on `JSONDecodeError` with a clarifying user-message append.

### Error handling
- Network/API errors: raise `commons.ai.client.AIError` (custom). View catches and re-renders capture form with an error banner and the user's text preserved.
- Empty `rows`: not an error. Render confirmation page with zero rows and a "no one parsed — try manual entry" link.
- Schema validation: validate the response against `ParseResult` shape with a small validator (no pydantic dependency required; `dataclasses` + manual checks are fine). On validation failure, raise `AIError`.

### Mocking in tests
- `commons/ai/client.py` reads a module-level `_OVERRIDE: Callable | None`. Tests do `client._OVERRIDE = fake_parse` in a fixture and reset in teardown. Cleaner than monkeypatching `anthropic.Anthropic`.
- Provide `tests/fixtures/parse_examples.py` with 6–10 canned `(input, expected_rows)` pairs covering: simple list, mixed statuses, late/absent phrases, ambiguous name, new name, typo, empty input, single name.

---

## 6. Railway deploy config

### Files

**`Procfile`:**
```
release: python manage.py migrate --noinput
web: gunicorn understory_commons.wsgi --log-file -
```

**`railway.toml`:**
```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "gunicorn understory_commons.wsgi --log-file -"
healthcheckPath = "/healthz/"
restartPolicyType = "ON_FAILURE"
```

**`requirements.txt`** (or `pyproject.toml` + `uv` lock; pick one — `pyproject.toml` preferred):
- `Django>=5.0,<6.0`
- `psycopg[binary]>=3.1`
- `gunicorn`
- `python-decouple` (chosen over `django-environ` for narrower surface)
- `anthropic`
- `whitenoise` (for any static files; minimal in V1)

### Settings split

`understory_commons/settings/base.py` — shared. Reads `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `SITE_URL` via `decouple.config`.

`understory_commons/settings/dev.py`:
- `DEBUG = True`
- SQLite default if `DATABASE_URL` unset
- `ALLOWED_HOSTS = ["*"]`

`understory_commons/settings/prod.py`:
- `DEBUG = False`
- Postgres via `dj-database-url` parsing of `DATABASE_URL`
- `ALLOWED_HOSTS` from env (comma-split)
- `SECURE_PROXY_SSL_HEADER`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`
- `whitenoise.middleware.WhiteNoiseMiddleware`

`DJANGO_SETTINGS_MODULE` selection via `manage.py` and `wsgi.py` reading `DJANGO_ENV` env var (default `dev`).

### Env vars (Railway dashboard)
- `DJANGO_ENV=prod`
- `SECRET_KEY` (generate)
- `ALLOWED_HOSTS=<railway-domain>`
- `DATABASE_URL` (auto-injected by Postgres plugin)
- `ANTHROPIC_API_KEY`
- `SITE_URL=https://<railway-domain>` (for magic-link URL composition)

### `.env.example`
Committed. Lists every required env var with placeholder values. `.env` is git-ignored.

### Healthcheck
`/healthz/` view in `core/views.py` — returns `200 OK` plain text, no DB query. Wired in `understory_commons/urls.py`.

---

## 7. Pre-commit / tooling setup

**`pyproject.toml`** sections:

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "DJ", "SIM"]
ignore = ["E501"]  # black handles line length

[tool.black]
line-length = 100
target-version = ["py312"]
```

**`.pre-commit-config.yaml`:**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/psf/black
    rev: 24.8.0
    hooks:
      - id: black
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: detect-private-key
```

Run `pre-commit install` as part of dev setup. README (or `docs/dev.md`) documents this; do not create the README in V1 unless asked.

**Conventional Commits** — enforced socially in V1, no commit-msg hook.

**Logging** — `LOGGING` dict in `settings/base.py` with a `commons.ai` logger at INFO. No `print()` anywhere; ruff rule `T201` can be added to enforce.

---

## 8. Build order

Each step is one commit. Stop and run tests at each numbered step.

1. **Repo init.** `pyproject.toml`, `.python-version`, `.gitignore` (Python + `.env`), `.env.example`, `.pre-commit-config.yaml`. Install pre-commit hooks. No Django yet.
2. **Django project skeleton.** `django-admin startproject understory_commons`. Split settings (`base/dev/prod`). `manage.py runserver` works against SQLite. `/healthz/` endpoint.
3. **Custom User model.** Create `accounts` app with `User`, `UserManager`, `AUTH_USER_MODEL` set in base settings. Migrate. Test: create a coordinator user via `User.objects.create_user`.
4. **Core models.** `Organization`, `TimestampedModel`. Register in admin. Test: create org.
5. **Program + Session.** Models, admin, `programs_visible_to` queryset helper. Tests for org-scoping.
6. **Magic-link auth.** `MagicLinkToken` model, `mint_magic_link` service, `magic_login` view, custom auth backend. Test: full mint -> consume cycle, expired token rejected, double-consume rejected.
7. **Coordinator account-creation UI.** `/accounts/facilitators/new/` form, render-link page, re-mint endpoint. Group seeding data migration. `@coordinator_required` decorator. Tests for role gating.
8. **Participant + AttendanceRecord models.** Append-only `save()` override on `AttendanceRecord`. Admin registration. Merge-participants admin action (sets `merged_into`, leaves history intact). Tests for append-only enforcement and merge.
9. **`commons/ai/client.py` skeleton + tests.** Interface, `_OVERRIDE` test hook, `AIError`, schema validation. No real Anthropic call yet — just the contract. Fixture-based tests pass.
10. **Anthropic integration.** Wire actual `anthropic` SDK call with the prompt. One smoke test that hits the API behind an env-gated marker (`pytest -m live`). Default test run mocks via `_OVERRIDE`.
11. **Attendance capture flow — happy path.** `capture`, `parse`, `confirm` views with HTMX partials. New-participant creation. Idempotency key wired. Tests for write path, idempotency replay, append-only behavior on resubmit.
12. **Disambiguation UI.** Ambiguous and existing-match branches in `_confirm.html`. Tests for each match_state.
13. **Manual fallback form.** `/manual/` view, checkbox table. Disabled-state when roster empty.
14. **Session detail + dashboard.** Coordinator dashboard listing programs + recent sessions. Facilitator dashboard listing only assigned programs. Session detail page showing latest attendance state per participant.
15. **Railway deploy.** `Procfile`, `railway.toml`, `whitenoise`, prod settings hardening. Push to Railway, run migrations, smoke test on the deployed URL with a seeded coordinator.
16. **Verification chain test pass.** Single test module that walks: coordinator creates facilitator -> facilitator consumes link -> submits attendance -> `AttendanceRecord` rows have correct `recorded_by`, `recorded_at`, `source`, `raw_input`, `llm_request_id`, and cannot be mutated. This test is the Phase 1 acceptance gate.

---

## 9. Open questions / deferred decisions

Sonnet should **stop and escalate** on these rather than guessing:

1. **Idempotency storage shape.** Plan specifies `submission_idempotency_key` column on `AttendanceRecord`. If during implementation it becomes obvious that a separate `AttendanceSubmission` parent row (with rows as children) is cleaner — escalate before refactoring; this affects the verification chain shape.
2. **Anthropic structured output mechanism.** Whether to use tool-use, JSON mode, or plain-text + `json.loads`. Decide based on what the SDK exposes most stably for Sonnet 4.6 at implementation time. Document the choice in `commons/ai/client.py` docstring.
3. **Token URL secrecy in re-mint flow.** Coordinator can re-mint at will. Should the page also show currently-active (unconsumed, unexpired) tokens, or only the freshly minted one? V1 default: only the fresh one. Escalate if the coordinator workflow demands listing.
4. **`pyproject.toml` vs `requirements.txt` for Railway.** Railway's Nixpacks supports both. Default to `pyproject.toml` with `uv` lock; if Nixpacks build flakes, fall back to `requirements.txt`.
5. **Disambiguation when LLM returns a `match_participant_id` for a participant that was merged after parse.** Edge case. Current plan: confirm view re-validates and surfaces a "this participant was merged into X — use X?" prompt. Escalate if implementation reveals a cleaner path.
6. **Session creation UX.** Plan covers attendance against an existing session but does not specify the session-creation UI. V1 minimum: coordinator creates sessions in admin or via a single `/programs/<id>/sessions/new/` form. Confirm with user before building anything richer.
7. **Org bootstrap.** First-ever coordinator account on a fresh deploy. Plan assumes a `createsuperuser`-equivalent management command that seeds an `Organization` + bootstrap coordinator. Confirm name (`bootstrap_org`) and parameters before adding.
8. **Live LLM test budget.** Whether `pytest -m live` runs in CI or only locally. Default: local only, no CI key. Escalate if user wants CI integration.
