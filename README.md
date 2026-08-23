# Usage

Private tracker of meter readings — water, electricity, gas, car mileage — for the
family houses, at https://usage.edgy.world. Readings are entered manually or extracted
from a photo of the meter (Claude vision); consumption is derived as the difference
between consecutive readings, evenly spread over skipped months.

Architecture is the Family Net template: FastAPI + vanilla JavaScript + PostgreSQL,
Docker blue/green deployment, Fernet-sealed sensitive columns, magic-link + passkey
sign-in. Code follows `/media/APPLICATIONS/coding_conventions.md`; the full design is
in `PLAN.md`.

## Layout

```
app/usage/
  main.py          AppFactory; module-level `app` for uvicorn
  handlers/        ApiRouter + one Pydantic DTO per file
  commands/        auth, passkeys, admin, readings, stats
  libraries/       database (psycopg3 + schema/migrations), crypto_box (Fernet +
                   blind index), settings_loader, email_sender, webauthn_box,
                   cbor_decoder, meter_reader (photo → values), static_page
  structures/      NamedTuples with to_dict()/from_dict(); AppException
  constants/       frozen-dataclass Constants singleton
  static/          index.html, app.js, ui.css, theme.js, icons.js — no build step
tests/             mirrors app/ 1:1, 100 % coverage required
deploy/            blue/green scripts, nginx conf, daily backup container
```

## Development

```bash
cp .env.example .env                      # fill in the secrets
docker compose up -d --build usage-app-blue
# or: bash deploy/deploy-local.sh
```

With `USAGE_DEV_AUTH_LINKS=true` the sign-in link is echoed in the API response, so
no SMTP is needed locally.

Checks (all must pass, coverage must be 100 %):

```bash
uv run --extra dev pytest tests/ --cov=usage
uv run --extra dev mypy .
uv run --extra dev ruff check .
```

## Deployment

Production: `ubuntu@45.85.249.159`, `/opt/usage`, blue on 127.0.0.1:8063, green on
127.0.0.1:8064, nginx switching colours (`deploy/nginx-usage.edgy.world.conf`).
The production `.env` lives only on the server.

```bash
bash deploy/deploy-from-local.sh
```

The deploy builds the idle colour, waits for `/healthz`, points nginx at it, then
stops the old colour. Migrations run at startup and must stay additive (both
colours briefly share the database).

Backups (our-stories pattern): the `usage-backup` container dumps the database
daily, sealed with `openssl aes-256-cbc` under `USAGE_BACKUP_PASSPHRASE` before
touching disk, into `/backups/<day-of-month>/` (~31-slot local rotation), then
copies to `s3://$S3_BACKUP_BUCKET/daily/usage/<date>/` — plus `monthly/` on the
1st. Restoring needs the passphrase AND the Fernet key; keep both in the password
manager.
