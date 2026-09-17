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
sensor alone and Ctrl+click (or a long press) adds and removes them. The solar's
two tiles work the same way — a click leaves production or consumption alone on
the chart, and a lone series gets the whole bucket rather than half of it. One
rule, written once, for both sets of tiles. On a phone the view drops its
heading — the bottom bar already names it — and the switches keep their sliders
but trade their words for icons.

Each control above the view is offered to the houses it can do something for, which it says
for itself (`data-needs`): the alert lines are the thermometers' alone, but the overlay redraws
every graph and the unit switch governs volumes as well as degrees, so a water-only house gets
both. **Previous** and **Thresholds** are icons rather than sliders, pressed for on, which is
what the graph icons beside them already meant — three controls that do the same
kind of thing now look like each other, and the row fits a phone.

The date bar carries an icon for each half the house actually has: thermometer,
drop, sun. Pressed is showing. They are a viewer's choice kept per browser, like
the unit switch, and they decide which graphs get the screen rather than what is
collected — a house measuring three things rarely wants to look at all three at
once. Turning every one of them off leaves the bar behind, since otherwise there
would be no way back.

The battery graph is drawn on the same holder the thermometers use, so the pointer gets the
same circle on the curve, the same label beside it and the same hairline stroke; one hover and
one line style to maintain rather than two that drift apart.

The solar tiles show **power** - what the panels are making this second - whenever Home
Assistant is pushing, and fall back to the last interval's energy when only the cloud feed is
running, which is the best a four-hourly feed can honestly offer.

One switch over the view picks the unit system for everything on it: **US** shows
Fahrenheit and gallons, **FR** shows Celsius, litres and cubic metres. It is a viewer's
choice, kept per browser, and it changes nothing that is stored — temperatures arrive as
the thermometer reports them and water is always held in cubic metres. **Previous**
overlays the period before the one on show, across every graph: dotted curves for the
thermometers, pale bars behind the water and the solar — and a bar's tooltip then carries both
readings under their own dates, since comparing them is the whole point of the overlay.

The water card carries its own **Running total** switch, which draws the water added up as
the period goes, ending at the figure in the heading — one line per period when the overlay
is on, so a week can be read against the week before it at every point rather than only at
the end. It shares the bars' axis rather than taking a second one: the line *is* the bars
added up, so a scale of its own would invite the reader to compare two heights whose
alignment we had invented. The honest price is that the ladder then climbs to the period's
total and the bars shrink under it, which is why it is a switch and why it is off by default.
It exists because a day's total is not legible from its bars: one quarter-hour can hold a
third of it, and the rest arrives in bars too short to see, let alone add up.

What a house measures is a decision, not a guess from the data: Settings, Houses, Edit
carries a switch for the thermometers, one for the water meter and one for the solar. Between
them they decide whether the Realtime page appears for that house at all, and which of the
settings panels are worth showing — a house with a water meter and no thermometer is
not offered thermometer settings. Existing houses were seeded from what they already
collect, so a new house needs its switches ticked once.

### Asking again

The view's three halves are fed by three things that move at three different speeds, so they
are asked for separately and on their own clocks rather than together on one timer. Every
series answers with two extra fields:

`next_poll_seconds` is **when it is worth asking again** — the moment the thing behind the
graph could first have something new, held between 30 seconds and 15 minutes. For the water
and the cloud solar that moment is exact and known here: the rows only change when the sync
loop pulls the feed, so the answer is its next due pull. For the two pushed feeds the cadence
belongs to Home Assistant and not to this app, so it is **measured** rather than assumed: each
push writes down how long it had been since the previous one (`houses.sensors_push_seconds`,
`enphase_live.push_seconds`), and the page is told to look again that long after the last one
landed. A gap longer than half an hour is an outage rather than a cadence and is not allowed
to teach the page to sleep through the afternoon. A house on thermometers pushing every ten
minutes is therefore asked roughly every 599 seconds and a gateway pushing every minute
roughly every 59, without either number being written down anywhere.

`stamp` is a short fingerprint of **everything that card draws** — its points, its latest
reading, its alert or its live block. The window's own end is deliberately not in it: `until`
is "now" and moves on every request, so folding it in would make every answer look new while
the graph it draws is identical to the pixel. The browser compares the stamp it has against
the one that came back and only rebuilds that card when they differ. Nothing else on the page
is touched: the period bar keeps its focus, and the other two graphs keep the pointer they
were following.

A background refresh shows no wheel — only a load asked for by hand does — and borrows no
button. A graph switched off is not asked for at all, and one switched back on is asked afresh
rather than reappearing at whatever it last said. The words that age on their own ("5 min
ago", and whether a tile has gone stale) are retouched on a minute's clock as text, without
redrawing anything, because a stamp that has not moved is no reason to leave a tile claiming
it was read five minutes ago an hour later.

Websockets were considered and declined. The whole view receives about one event a minute at
its busiest; a socket would buy under a minute of latency in exchange for `Upgrade` headers in
nginx, a reconnect-and-resync path that duplicates the polling code, and every connection
dropped on each blue/green switch.

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
the last range the view refreshes itself; an earlier period cannot change, so it
does not. See "Asking again" below for when it asks and what it redraws.

### When a thermometer was last heard from

`last_changed` keys the sample, which is what makes a value re-sent unchanged a
no-op rather than a duplicate row every ten minutes. It is the wrong instant for
the tile, though: it answers "how long has it been this warm", and a room that
holds steady is not a room whose thermometer has died.

Home Assistant cannot answer the other question directly, which took a while to
establish. It keeps three instants - `last_changed` (the value changed),
`last_updated` (the value **or an attribute** changed) and `last_reported`
(written at all, changed or not) - and `last_reported` reads exactly like the
one wanted. It is not: the SwitchBot and Govee integrations only write on a
change, so all three sit at the same instant. Measured on a real Govee, fifty-one
minutes with the three identical to the second.

So it is answered sideways, in the Home Assistant template: a thermometer
publishes temperature, humidity and a charge, and whichever of those moved most
recently is proof the device was heard from at least that recently. Outdoors the
humidity moves constantly while the temperature holds a step, which is exactly
where the tile was wrong. The entities are derived by name, like the battery, so
nothing is added to the entity map.

That is a lower bound rather than the instant itself; the exact answer is the
signal-strength entity, which wobbles on every advertisement but is a diagnostic
one and disabled by default. The template already looks for it, so enabling it
per device sharpens the answer with no change here.

Whatever the template works out travels as `reported_at` and belongs to the
thermometer rather than to any reading, so only the latest is kept
(`sensors.reported_at`, beside the charge).

The tile counts its age, and its three-hour staleness, from `reported_at`. The
two are far apart for anything slow: the outdoor SwitchBot resolves to a fifth
of a degree, so it sits half an hour on one number while reporting every minute,
and counting from `last_changed` had the tile claim it had not been heard from
since - which is exactly what a dead thermometer looks like. The reading's own
age is not lost, it is simply not the headline: the tile's tooltip carries
"Reading unchanged since ...", as a clock rather than a count, since a title
attribute is not retouched by the minute.

A push that does not carry `reported_at` - an automation still on the older
template - leaves the column unset rather than standing in the push's own
arrival, which would claim a freshness the thermometer has not vouched for. The
tile then falls back to `last_changed`, exactly as it behaved before.

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

A background thread wakes every minute and asks which feeds are due; each one is pulled
at most every fifteen minutes. Looking often and pulling rarely is what makes a feed added
or reset between two pulls show something straight away rather than sitting empty for a
quarter of an hour, which reads exactly like a feed that does not work. Each pull takes
the last two days — EyeOnWater
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

That `Timezone` column is why `tzdata` is a dependency. EyeOnWater writes legacy IANA aliases
(`US/Pacific`, not `America/Los_Angeles`), and a slim image's tz database leaves the aliases
out — the canonical names resolve and the alias does not. Falling back to UTC there filed
every reading seven hours from where it belonged, silently, which is how four years of it got
stored before anyone noticed. A zone that cannot be resolved now stops the export and says so:
no data beats wrong data that looks right.

A house always has some quiet stretch in any 24 hours — asleep, out, every tap shut — so 24
hours of readings without a single zero among them means water is running that nobody turned
on. When that happens the users who asked for it (Settings, Water) get one email naming the
quietest reading of the stretch and what it drew in total.

It is a **rolling** window, not a calendar day: a stretch running from one afternoon to the
next counts exactly as much as one from midnight to midnight, and grouping by day would step
straight over it. The window ends at the newest reading rather than at this instant, since
EyeOnWater publishes hours late and a window ending now is always half empty at the near end;
a window that is only partly reported proves nothing either, so the readings must be many
enough and spread far enough apart to cover it. The feed remembers whether it is already
reported, so the email follows the crossing rather than every quarter of an hour, exactly as
the thermometers' alerts do.

The same 24 hours answer a second question, because measuring them twice would leave two
rules able to disagree about the window: **did too much go through?** A meter can carry a
limit (Settings, Water, Edit), typed in whatever unit the viewer reads volumes in and stored
in cubic metres like everything else. It is opt-in — no limit, no alert — because a house can
run every tap it owns all afternoon without a drop of it being accidental, and because a slow
leak can pass unnoticed while never adding up to much. The two rules catch different things
and neither subsumes the other. This one is edge triggered as well, or a fortnight with the
sprinklers on would mail every quarter of an hour — and moving the limit re-arms it, exactly as
moving a thermometer's range does, since the flag standing against a house was the verdict on
the old number and would otherwise keep the graph red until the next pull. The limit rides along in the Realtime title
beside the period's total — quietly while the house is under it, and in the warning colour once
it is not, since the email announces the crossing but the page is where it gets looked into.

Against four years of one real meter the leak rule fires seven times — stretches of 27, 29, 90,
385, 31, 120 and 260 hours. The two longest drew around twice the ordinary daily volume
throughout. Grouping the same data by calendar day instead finds only five of the seven,
which is the case for the rolling window in one line.

The point of storing it all is ownership: once a month is in `water_points` it never has to be
asked for again, whatever the portal does next. Readings are keyed by feed and instant, so an
overlapping export is absorbed rather than counted twice. The Realtime view draws them as bars
summed per bucket — water is a counter, so the scale starts at zero and an empty bucket is a
gap, not a dip — under the same range tabs, offset and overlay as the thermometers, so both
graphs always show the same window. The axis ladder is built in the unit it will be read in
rather than in the cubic metres underneath, since a step that is round in m³ lands on 26 and
53 gallons.

## Realtime: solar (Enphase)

A house's solar arrives two ways at once, and they are good at opposite things. The **cloud
feed** talks to Enphase's developer API (v4) and owns the years: it is the only one that can
answer for 2022, and it is metered, slow and rationed. The **push feed** is Home Assistant
reading the gateway on the house's own network every minute: it is free, live, and knows
nothing that happened before it was switched on.

Neither is sufficient alone. An Envoy only answers on the LAN and this app runs on a VPS that
has never been on it, so without the push there is nothing live; and a gateway remembers no
history worth the name, so without the cloud there is nothing behind today. A house can run
either or both, and most will want both.

A feed is one system of one Enphase application, added by an admin in Settings, Solar. Three
secrets identify the application — client id, client secret, API key — and the fourth is
short-lived: **Authorise** opens Enphase, the owner approves the application there, and the
code it prints is pasted back. It is exchanged for a token pair while the form is still open,
because those codes expire in minutes; the same call then asks the account which systems it has
and reads a day, so a wrong key is refused in the form rather than hours later in `last_error`.

```
POST /oauth/token?grant_type=authorization_code&code=...   Basic client_id:client_secret
POST /oauth/token?grant_type=refresh_token&refresh_token=...  the pair rotates every time
GET  /api/v4/systems                                       key= + Bearer
GET  /api/v4/systems/{id}/telemetry/production_meter        ?start_at=&granularity=day
GET  /api/v4/systems/{id}/telemetry/production_micro        only if there are no production CTs
GET  /api/v4/systems/{id}/telemetry/consumption_meter
GET  /api/v4/systems/{id}/telemetry/battery
GET  /api/v4/systems/{id}/energy_lifetime                   daily totals, whole system life
GET  /api/v4/systems/{id}/consumption_lifetime
```

Two credentials guard every call and they are not interchangeable: the API key says which plan
the request is billed to, the bearer token says whose account it may read. Both fail with a 401
and they are fixed differently, so Enphase's own words are passed straight through into
`last_error`. A 401 is answered exactly once, by refreshing and retrying.

**The refresh token rotates on every use.** The pair that comes back replaces the one that was
sent, and the old one is dead the moment it is used. So the tokens are written back whether the
pull succeeded or not — the save sits in a `finally`, not on the happy path, because a rotated
token thrown away by a later failure locks the account out until a person authorises it again by
hand. A refresh token also lasts about a month, so a feed left paused for longer needs a fresh
code; that is what the panel means when it says the authorisation has lapsed.

Unlike the water portal, **this API is metered**, and that one fact shapes everything else. The
free tier is a thousand calls a month, a tick costs six, and running hourly would spend the
month by the eighth. So the feed has no fixed interval: it works out its own from what is left
of the allowance and how much of the month is left to spend it over, held between a quarter of
an hour and six. An account on a larger plan raises the budget on the feed and the pace opens up
on its own; a spent one waits for the turn of the month rather than knocking on a door that
answers 429.

There is a **second, independent limit underneath it**: ten calls a minute. Pacing the ticks
does nothing for that one, because the burst happens inside a single tick — a first tick asks for
six calls for the recent days, two for the history and three per day of the fine walk, close to
twenty in a row. So a sliding window sits under the client and simply will not let the burst out:
the call that would be the tenth in a minute waits for the first to age out instead. The window
slides rather than resetting on the minute, since a fixed bucket lets through twice the ceiling
across a boundary — ten calls at 11:59:59 and ten more at 12:00:01 — which is exactly the shape
of a backfill tick.

**The window lives in the database** (`api_calls`), not in memory, because the ceiling belongs to
the API key and this app runs as two processes: during a blue/green deploy both colours are up
at once, and a window each would let exactly twice the ceiling through. The background sync and
an admin submitting the feed form are two more claimants on the same allowance. The database is
the only thing all of them share.

That makes the count a read-modify-write two processes can race — both read "eight taken", both
decide there is room, both go — so it is taken inside one transaction behind a Postgres advisory
lock. Every time involved is `clock_timestamp()` and never `now()`: `now()` is the transaction's
*start* time and holds still for its whole length, and this transaction may have spent seconds
queueing for the lock, so stamping a call with the moment its transaction began would age it out
of the window early and let the ceiling drift upwards under load. That was not theoretical — it
let ten through in a nine-call window the first time it was measured.

The ceiling is set to nine rather than ten, which buys the margin that covers the gap between
our clock and theirs: we stamp a call when the slot is granted, and Enphase counts it when the
request lands a moment later. Against four processes racing on a compressed window the
timestamps enforcement uses never exceeded nine, and arrival times never exceeded ten — the
plan's actual limit. The effect in normal running: a steady tick of six calls never waits at
all, a first tick spends about a minute mostly asleep, and nothing ever comes back 429. The feed
form passes the same wait budget and only reaches it if a backfill happens to be bursting at
that exact moment, in which case it says so instead of hanging.

None of that ceiling matters much once the push feed is running: the live edge comes free off
the LAN, and the cloud feed is left doing the one job only it can do - the years - for a couple
of calls a month.

### The push feed, and why the two are never added together

Home Assistant posts to `/api/ingest/power` on the same house token the thermometers use
(`deploy/home-assistant.yaml` carries both). What it sends is **readings, not rates**: the
gateway's lifetime counters in watt-hours, which the app differences to get the energy of the
interval between two pushes - the same trick it uses on a meter reading. That is what makes a
dropped push cost nothing, where a reported rate would turn every one into a hole. It also
sends instantaneous power, which is what the tiles show and the whole reason for pushing at all.

Two things it refuses to draw. A counter that has gone backwards is a replaced or reset gateway,
not a house that generated negative electricity, so it starts a fresh baseline and charts
nothing. And a gap longer than an hour is an outage rather than an interval: charting it would
put one enormous bar where a quiet night belongs.

Both feeds describe the same panels, so **the series never sums them**. Adding them would double
every reading a house collects both ways. Preferring one source wholesale would be wrong too:
Home Assistant only knows what it has been up for, and the cloud is exactly what covers the
hours it was not. So the two are bucketed separately and the live one is laid over the cloud's,
a bucket at a time - live where there is live, cloud underneath. That is the `FULL OUTER JOIN`
in `_series_query`, and it is why they must be grouped before they meet.

The push feed appears as a second row in Settings, Solar, with nothing to configure and only
its own pulse to report - a silent typo in the automation otherwise looks exactly like a working
one.

### The cloud feed's history

The same arithmetic decides the resolution of the history, which is why there are two passes.
The lifetime endpoints answer a multi-year range in **one call each**, so the daily totals of the
whole system's life are bought on the first tick and never asked for again. Quarter-hourly
telemetry costs **three calls for every single day** walked, so it walks back a fortnight — enough
to fill the day and week views — and then stops for good. Both resolutions live in
`enphase_points` and `span_minutes` keeps them apart: the day and week views read the
quarter-hours, the month and year views read the daily rows, and no query ever reads both, or an
hour would be counted inside its own day twice.

Production CTs are usual but not universal, and a system without them is **not refused** by the
meter endpoint — it is answered with an empty day, which looks exactly like night. That cost a
real feed its production: a fallback that waited for a refusal never fired, and the system
collected consumption and nothing else. So an empty answer falls through to the microinverters
too, which always know what they made, and the endpoint that finally says something is written
down on the feed (`production_path`). Only the learning costs the extra call; once the path is
known nothing is tried twice, and a system that really is idle at 3am is not re-asked for ever.
Both quiet teaches nothing, so the question simply stays open until a day with some daylight
in it.

Production and consumption are counters, so their buckets are sums and the graph draws them as
paired bars — what the panels made beside what the house drew, on one scale, since that
comparison is the whole question. The battery is a level, not a counter: it is averaged over a
bucket and drawn as a line across the full 0–100, so a flat week does not look like a cliff. It
is also the one thing the lifetime endpoints cannot supply, so the battery card goes back only
as far as this app has been collecting — on the month and year views it says so rather than
showing an empty graph.

Everything is stored in kilowatt-hours, as the rest of the app stores electricity, converted from
the watt-hours Enphase reports at the client boundary. An interval is filed under the instant it
*started*, since Enphase reports the far end and a bar covering 10:00–10:15 belongs at 10:00. The
length of an interval is measured from the gap between consecutive ends rather than assumed:
`granularity` names the range asked for, not the resolution answered, and the same shape carries
five-minute microinverter data and quarter-hourly meter data.

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
