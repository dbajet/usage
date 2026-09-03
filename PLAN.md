# usage.edgy.world — Implementation Plan

## Context

A private web application to track utility usage (water, electricity, gas) and car mileage
for several houses (Fremur, Dougmar, …), replacing a Google Sheets workbook. Data enters as
meter readings — cumulative counter values ("compteur") — either typed into a form or
extracted from a photo of the meter. Consumption is derived as the difference between
consecutive readings. The app displays: the list of measurements, per-kind tables of usage
per month/year (with annual totals), and trend graphs.

The architectural template is `/media/APPLICATIONS/git_dbajet/family_net` (same author, same
server), and all code follows `/media/APPLICATIONS/coding_conventions.md`.

- Repo: `/media/APPLICATIONS/git_dbajet/usage` (empty; remote `git@github.com:dbajet/usage.git` to be added)
- Production: `ubuntu@45.85.249.159`, directory `/opt/usage`, site `https://usage.edgy.world`
- Stack: Docker (blue/green) + FastAPI + vanilla JavaScript + PostgreSQL 16
- Language: English only (no i18n layer)
- Photo readings: auto-extracted by the Claude API (vision), pre-filled into the form, user confirms
  before saving. Photos are transient: processed in memory for extraction, never stored.

## Domain model

- **House**: name (sealed). Users are linked to houses; a user only sees the houses they are linked to.
- **Meter**: belongs to a house; `kind` ∈ {water, electricity, gas, mileage}; label (sealed — e.g.
  "EDF", "GDF", "Water", "Peugeot 208"); unit (kWh, m³, km). Several meters of the same kind per
  house are allowed (multiple cars). A meter has **1 or 2 registers** (e.g. electricity "HC" / "HP",
  labels sealed). Register count can change over a meter's life (spreadsheet shows EDF switching to
  HC/HP in Jan-2026) → model registers as rows with an `active` flag; a replacement meter or new
  register starts a new counter baseline (`initial value` on the register).
- **Reading** (measurement): meter + date (day precision, aggregated monthly) + one numeric value per
  active register + `source` (manual | photo). The photo itself is discarded after extraction —
  only the confirmed values are persisted.
- **Consumption** (derived, never stored): per register, `reading(m) − previous reading`. When months
  were skipped, the delta is **evenly distributed** over the unmeasured months
  (`delta / month_gap` per month, matching sheet #1 vs #2). Register deltas are summed for the meter
  total (HC + HP). Handles counter resets/new baselines by starting from the register's initial value.

## Database schema (all sensitive columns `*_sealed`, blind indexes `*_hash`)

`schema_migrations, users (email_sealed, email_hash UNIQUE, is_admin), sessions (token_hash),
login_links (token_hash, email_hash, expires_at, used_at), passkeys, houses (name_sealed),
user_houses (user_id, house_id UNIQUE pair), meters (house_id, kind, label_sealed, unit, position, active),
registers (meter_id, label_sealed, initial_value, position, active),
readings (meter_id, read_on DATE, source, created_by),
reading_values (reading_id, register_id, value NUMERIC(12,2), UNIQUE pair)`

Schema + numbered additive migrations live in `libraries/database.py::initialize()` exactly as in
family_net (`CREATE TABLE IF NOT EXISTS` list + `(version, name)` migration tuples) — required by the
blue/green overlap (migrations must stay additive). Seed: first admin user `dbajet@gmail.com`.

## Backend structure (mirror of family_net, `app/usage/`)

```
main.py                       AppFactory + module-level `app`; lifespan → database.initialize();
                              security-header middleware; AppException handler; /healthz; / → StaticPage
handlers/
  api_router.py               class ApiRouter, imperative add_api_route() under /api; thin methods:
                              resolve session cookie → delegate to a command
  <one Pydantic BaseModel DTO per file>
commands/
  auth_command.py             magic link + sessions
  passkey_command.py          WebAuthn registration/assertion
  admin_command.py            users, houses, user↔house links, meters/registers (admin-gated)
  reading_command.py          CRUD readings + photo intake + LLM extraction call
  stats_command.py            consumption computation, month/year tables, graph series
libraries/
  settings_loader.py          env → Settings NamedTuple (USAGE_* prefix, DATABASE_URL, SES_*, ANTHROPIC_API_KEY)
  database.py                 psycopg3, thread-local connection, fetch_one/fetch_all/execute/transaction,
                              schema+migrations+seed, encrypt/decrypt/blind_index/decrypt_rows
  crypto_box.py               Fernet + HMAC blind index (copy of family_net pattern)
  email_sender.py             SES SMTP, sends the magic sign-in link
  meter_reader.py             Claude API vision call: photo bytes → {value(s), confidence}; model and
                              key from Settings (consult the claude-api skill at implementation time)
  webauthn_box.py, cbor_decoder.py   copied/adapted from family_net (hand-rolled WebAuthn)
  static_page.py              index.html with __BUILD__/__VERSION__ substitution
structures/                   Settings, SessionUser, AppException, per-domain NamedTuples (to_dict/from_dict)
constants/constants.py        frozen-dataclass singleton: cookie names, kinds, units, limits, first admin email
```

Key conventions honored: pure OOP, one class per file, handlers→commands→libraries→structures/constants
one-way imports, NamedTuples over dicts, mypy strict, `result` naming, sync handlers (no gratuitous async).

## Authentication

- **Magic link**: `POST /api/auth/request-link` — always answers "If that email has an account, we sent
  a link" (anti-enumeration + timing padding, as family_net); emails
  `https://usage.edgy.world/?login=<token>`; token stored sha256-hashed in `login_links`, 15-min TTL,
  single use. Frontend detects `?login=`, calls `POST /api/auth/verify-link`, strips the URL via
  `history.replaceState`. Sign-in never creates accounts — only admins create users.
- **Passkeys**: same flow as family_net (options → create/get → verify), challenge kept in a short-lived
  encrypted httponly cookie.
- **Session**: opaque token, sha256-hashed in `sessions`, 30-day httponly/secure/lax cookie.
- **Dev mode**: `USAGE_DEV_AUTH_LINKS=true` echoes the link in the API response (no SMTP locally).
- **Roles**: `users.is_admin` boolean (simpler than family_net's context system — no role switching
  needed). Admin-only endpoints guard with `_require_admin()`; house-scoped endpoints guard membership
  via `user_houses`.

## API surface (all JSON under /api)

- auth: `request-link, verify-link, logout, session`
- passkeys: `options, verify` (sign-in) + `POST/GET/DELETE /passkeys` (management)
- dashboard: one `GET /api/dashboard` returning houses, meters, registers for the session user
  (family_net's single-payload pattern; 20 s polling on the client)
- readings: `GET /readings?house_id&meter_id&page`, `POST /readings`, `PUT/DELETE /readings/{id}`,
  `POST /readings/extract` (photo in request body → LLM → suggested values; photo discarded after the call)
- stats: `GET /stats/tables?house_id` (per kind: years×months consumption + annual totals),
  `GET /stats/series?house_id` (monthly series per meter for the graph)
- admin: `GET/POST/PUT /users`, `GET/POST/PUT /houses`, `POST/DELETE /user-houses`,
  `GET/POST/PUT /meters` (incl. registers)

## Frontend (static/, no build step — family_net pattern)

- `index.html` — public section: minimal sign-in form (email for magic link + "Use a passkey" button),
  nothing else. Gated app shell `#app hidden` with nav to three views:
  - **view-entries**: house/meter selector, paginated readings table (date, meter, value(s), source),
    add/edit modal with file input → `POST /readings/extract` pre-fills the value field(s) for
    confirmation (client-side preview only; the photo is not kept); manual entry always possible.
  - **view-stats**: per kind — the #4-style table (rows = years, columns = Jan…Dec + total) and the
    #5-style trend graph: hand-rolled SVG multi-series line chart (no chart library, consistent with
    conventions' "prefer stdlib/no deps"), one series per meter, secondary right axis for
    small-magnitude series (water), month ticks on the x-axis. Consult the dataviz skill before coding it.
  - **view-settings**: passkey management for everyone; admin-only panels for users, houses,
    user↔house links, meters/registers (client hides them, server enforces).
- `app.js` — vanilla, `api()` fetch wrapper with error banner + busy buttons, `showView()` show/hide
  routing, string-template rendering with `esc()`, `data-label` responsive table collapse.
- `ui.css` + `theme.js` — token-based light/dark theme, adapted from family_net's design language.
- `StaticPage` cache-busting via `?v=__BUILD__`.

## Docker & blue/green deployment

- `Dockerfile`: python:3.12-slim, pip install requirements.txt, uvicorn on port **8063** internally.
- `docker-compose.yml`: `usage-app-blue` (bind `127.0.0.1:8063`), `usage-app-green` (`127.0.0.1:8064`),
  `usage-db` (postgres:16-alpine, internal only, healthcheck, `restart: unless-stopped`), and the
  `usage-backup` sidecar following the **our-stories daily/monthly pattern**
  (`/media/APPLICATIONS/git_dbajet/our-stories/pilot/backup/`): postgres:16-alpine + aws-cli + openssl
  image; `backup.sh` runs once at container start then every 86400 s. Each run: `pg_dump` piped through
  `openssl enc -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE` (the dump never touches disk
  unencrypted) into `/backups/<day-of-month>/` — local slots rotate over ~31 days — then `aws s3 cp`
  to `daily/usage/<date>/`, plus `monthly/usage/<date>/` when the day is the 1st. As in family_net,
  compose maps the AWS credentials and `USAGE_BACKUP_PASSPHRASE` from the single `.env` into the
  backup service only — the app containers never receive backup-bucket keys. Volumes: `usage_db`,
  `usage_backups` (no images volume — photos are never stored). Ports 8063/8064 chosen to avoid family_net's 8053/8054
  on the same server — verify they are free during first deploy.
- `deploy/deploy-from-local.sh`: checks the local branch is pushed, then runs the server-side
  script over ssh on `ubuntu@45.85.249.159`; the server pulls the branch into its `/opt/usage`
  clone, so production always runs the last pushed commit.
- `deploy/deploy-prod.sh`: family_net's colour switch verbatim, adapted names/ports — build idle
  colour, start with `--no-deps`, poll `/healthz`, `sed` the nginx upstream in
  `/etc/nginx/sites-available/usage.edgy.world`, reload, stop old colour, prune images.
- `deploy/nginx-usage.edgy.world.conf`: upstream on 8063, HTTPS via certbot, rate limit on
  `/api/auth/`, `client_max_body_size 15m` (base64 photos), CSP/HSTS here, X-* headers from middleware.
- Production `.env` lives only on the server (`USAGE_COOKIE_SECURE=true`, `USAGE_DEV_AUTH_LINKS=false`,
  `USAGE_BASE_URL=https://usage.edgy.world`, `USAGE_ENCRYPTION_KEY`, `USAGE_DB_PASSWORD`, SES +
  Anthropic keys, and the backup settings `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`,
  `S3_BACKUP_BUCKET`, `USAGE_BACKUP_PASSPHRASE` — the passphrase kept in the password manager along
  with `USAGE_ENCRYPTION_KEY`, since restoring needs both). Repo carries `.env.example` only.
  Repo carries `.env.example` only — never commit secrets (family_net's `.env` mishap not repeated).

## Tooling & tests

- `pyproject.toml`: fastapi, uvicorn, pydantic, psycopg[binary], cryptography, anthropic; dev extras
  mypy (strict), pytest, pytest-cov, ruff (line 120, py312). Single source of deps; `requirements.txt`
  generated to match (no pillow-style drift).
- Tests mirror the source tree 1:1; 100 % coverage; one named test per method; `tested/result/expected/
  exp_calls` naming; `side_effect`-only mocks verified via whole-list `mock_calls` equality;
  `reset_mocks()` closures; `is_namedtuple`/`is_dataclass` helpers in `tests/conftest.py`.
- Checks: `uv run --extra dev pytest tests/ --cov=usage`, `uv run --extra dev mypy .`,
  `uv run --extra dev ruff check .`

## Implementation order

1. **Scaffold**: pyproject, Dockerfile, compose, `.env.example`, README, `.gitignore`; add git remote;
   first commit.
2. **Foundations**: constants, structures (Settings, SessionUser, AppException, domain tuples),
   settings_loader, crypto_box, database (schema + seed), static_page — with tests as each lands.
3. **Auth**: email_sender, auth_command (magic link, sessions), webauthn_box + cbor_decoder +
   passkey_command; api_router auth routes; minimal index.html with working sign-in.
4. **Admin**: admin_command + routes + settings view (users, houses, links, meters/registers).
5. **Readings**: meter_reader (Claude vision), reading_command + routes + entries view.
6. **Stats**: stats_command (gap-distribution consumption algorithm — unit-tested against the
   spreadsheet's numbers), tables + SVG graph in the stats view.
7. **Polish & checks**: 100 % coverage, mypy strict, ruff clean.
8. **Deploy**: nginx conf + certbot on the server, `/opt/usage`, `.env`, DNS `usage.edgy.world`,
   first blue/green deploy, smoke test (sign in, add reading via photo, check stats).

## Verification

- Local: `docker compose up` → sign in with dev link echo, create house/meter, post readings
  replicating the spreadsheet's EDF/GDF/Water columns, verify the month/year table equals sheet #4 and
  consumption matches #1 (including a skipped-month case and the HC/HP split of #3).
- `pytest` 100 % coverage, `mypy` strict clean, `ruff` clean.
- Production: `deploy-from-local.sh`, `/healthz` on the new colour, sign-in via a real emailed link,
  passkey registration, photo extraction round-trip.
- Backups: after first deploy, confirm `/backups/<day>/db_usage.sql.enc` appears and the
  `daily/usage/<date>/` S3 object lands; restore-test once (`openssl enc -d ... | psql` into a
  scratch database) to prove the passphrase + key pair actually recovers the data.
