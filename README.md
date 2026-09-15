# Usage

Private tracker of meter readings — water, electricity, gas, car mileage — for the
family houses, at https://usage.edgy.world. Readings are entered manually or extracted
from a photo of the meter (Claude vision); consumption is derived as the difference
between consecutive readings, evenly spread over skipped months.

Architecture is the Family Net template: FastAPI + vanilla JavaScript + PostgreSQL,
Docker blue/green deployment, Fernet-sealed sensitive columns, magic-link + passkey
sign-in. Code follows `/media/APPLICATIONS/coding_conventions.md`.

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

## Realtime

Each thermometer's current reading sits on a tile under its own graph, in the
colour of its curve: the tiles are the legend as well, so a click shows that
sensor alone and Ctrl+click (or a long press) adds and removes them. On a phone
the view drops its heading — the bottom bar already names it — and the switches
keep their sliders but trade their words for icons.

One switch over the view picks the unit system for everything on it: **US** shows
Fahrenheit and gallons, **FR** shows Celsius, litres and cubic metres. It is a viewer's
choice, kept per browser, and it changes nothing that is stored — temperatures arrive as
the thermometer reports them and water is always held in cubic metres. **Previous**
overlays the period before the one on show, across both graphs: dotted curves for the
thermometers, pale bars behind the water — and a water bar's tooltip then carries both
readings under their own dates, since comparing them is the whole point of the overlay.

What a house measures is a decision, not a guess from the data: Settings, Houses, Edit
carries a switch for the thermometers and one for the water meter. Between them they
decide whether the Realtime page appears for that house at all, and which of the two
settings panels are worth showing — a house with a water meter and no thermometer is
not offered thermometer settings. Existing houses were seeded from what they already
collect, so a new house needs its switches ticked once.

## Realtime: sensors (Home Assistant)

Thermometers reach the app the other way round from meter readings: Home
Assistant pushes them. Every ten minutes an automation POSTs the current value
of each listed entity to `/api/ingest/samples`, authenticated with the house's
sensor token (Settings, Houses, Edit, "Sensor token" - admins only, shown once, only
its hash is stored). The Home Assistant side is `deploy/home-assistant.yaml`.

Unknown entities become sensors on their own, named by the entity map in that
file; users rename, reorder or hide them in Settings, Sensors (there is no
delete: a deleted sensor would only come back on the next push). Samples are keyed by the instant the value
last changed, so a value re-sent unchanged is not a duplicate. The Realtime view
shows the latest values and a trend over a day, a week, a month or a year, with
averages per 10-minute, hourly, 6-hour or daily bucket and the low-high band. On
the last range the view refreshes itself every five minutes; an earlier period
cannot change, so it does not.

Each push also carries the charge of the thermometer that took the reading -
the battery entity is derived from the temperature one, `_temperature` replaced
by `_battery` - and the tile shows it as a small battery filled to its level,
turning red at 20 % or less. A thermometer with no such entity simply shows none.

A sensor can carry an alert range (Settings, Sensors, Edit): the "Thresholds"
switch draws those bounds across the graph as dashed lines in the sensor's own
colour, and a user who turns the house's switch on gets an email when a push
takes a thermometer out of its range. The sensor remembers which side it is on,
so the email follows the crossing, not every push that stays out of range.

## Realtime: water (EyeOnWater)

The water meter reports to EyeOnWater, not to us, and EyeOnWater has no documented API.
So the app drives the one thing a person can see working in the browser: the portal's
**Export Data** button. Four calls — sign in, ask for a CSV over a date range, poll the
task, download it — and that is the whole of what the background sync ever touches.

```
POST /account/signin                       form username/password, session cookie
GET  /reports/export_initiate?...          -> {"task_id": "task:..."}
GET  /reports/export_check_status/task:... every 2 s until {"state": "done"}
GET  the result URL                        the CSV, off on a presigned host
```

A feed is one meter of one EyeOnWater account, added by an admin in Settings, Water
(the panel appears once the house has its water switch on): host, username and password
(sealed, never shown again). The meter uuid is left empty — creating the feed asks the
account what meters it has, through the one call outside the export flow:

```
POST /api/2/residential/new_search   {"query": {"match_all": {}}}
```

That call earns its place. The portal shows a nineteen-digit meter uuid next to a
nine-digit meter id, and an export for the wrong one does not come back with a refusal:
it dies inside EyeOnWater's own task and reports `list index out of range`. Asking is
cheaper than a person copying, and an account with several meters is answered with the
list of uuids to pick from. Creating a feed then reads a day back over the export path
too, so a bad password or an account the export refuses is caught in the form rather than
hours later in `last_error`.

A background thread pulls every fifteen minutes: the last two days each time — EyeOnWater
publishes a few hours late and re-estimates rows afterwards, and re-asking repairs them for
free — plus, until the history has been walked, four month-long chunks going backwards. The
walk ends after two barren chunks in a row, since how far back a utility keeps its data is
not knowable in advance. Each feed is claimed (`claimed_until`) before it is pulled, so the
blue/green overlap cannot import twice; a failure lands in `last_error` and the loop goes on.

Two things the CSV teaches, both of which the parser relies on: `export_unit` governs the
`Flow` column only — `Read` stays in the meter's own unit (CCF for a US meter) — so both
columns are converted from the unit the CSV itself names, into cubic metres. The export is
asked for in `Gallons`, the value the portal's own button sends; `Cubic Meters` and `CM`
work too, and none of them change a stored number. And `Read_Time`
is local time with no offset beside a `Timezone` column, so on the autumn fall-back the hour
repeats; the rows arrive in order, so a moment that fails to move forward is the second pass
through it and takes `fold=1`.

The point of storing it all is ownership: once a month is in `water_points` it never has to be
asked for again, whatever the portal does next. Readings are keyed by feed and instant, so an
overlapping export is absorbed rather than counted twice. The Realtime view draws them as bars
summed per bucket — water is a counter, so the scale starts at zero and an empty bucket is a
gap, not a dip — under the same range tabs, offset and overlay as the thermometers, so both
graphs always show the same window. The axis ladder is built in the unit it will be read in
rather than in the cubic metres underneath, since a step that is round in m³ lands on 26 and
53 gallons.

## Historical data

The spreadsheet exports (`fremur_edf_gdf_eau.csv`, `dougmar_edf_gdf_eau.csv`)
are untracked — personal data stays out of git — so copy them to `/opt/usage`
by hand (`scp`) before importing on the server. Import them once into the
running stack (locally or on the server) with:

```bash
bash deploy/import-history.sh
```

The import creates the house, its EDF/GDF/Water meters and registers from
the "Arrivee" baselines, and one reading per month from the cumulative
counters. A counter that drops starts a replacement register (Dougmar's water
meter, Oct-2015); the HC/HP columns switch the electricity meter to two
registers (Fremur, Jan-2026). It refuses to run for a house that already
exists.

## Deployment

Production: `ubuntu@45.85.249.159`, `/opt/usage`, blue on 127.0.0.1:8063, green on
127.0.0.1:8064, nginx switching colours (`deploy/nginx-usage.edgy.world.conf`).
The production `.env` lives only on the server.

```bash
git push                            # production deploys the last pushed commit
bash deploy/deploy-from-local.sh    # runs the server deploy over ssh
```

Nothing is copied from your machine: the wrapper refuses a detached HEAD or an
unpushed branch (and asks before deploying anything but `main`), then runs
`deploy/deploy-prod.sh` in the git clone at `/opt/usage` over ssh. That script
refuses to run as anyone but the clone's owner, a missing or shallow clone, a
detached HEAD, a branch other than the one deployed from, and local changes,
then fast-forwards the branch. The deploy builds the idle colour, waits for `/healthz`, points nginx at it, then
stops the old colour. Migrations run at startup and must stay additive (both
colours briefly share the database).

Backups (our-stories pattern): the `usage-backup` container dumps the database
daily, sealed with `openssl aes-256-cbc` under `USAGE_BACKUP_PASSPHRASE` before
touching disk, into `/backups/<day-of-month>/` (~31-slot local rotation), then
copies to `s3://$S3_BACKUP_BUCKET/daily/usage/<date>/` — plus `monthly/` on the
1st. Restoring needs the passphrase AND the Fernet key; keep both in the password
manager.
