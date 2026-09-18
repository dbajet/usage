from __future__ import annotations

import logging
import math
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.email_texts import EmailTexts
from usage.libraries.ingest_token import IngestToken
from usage.libraries.series_pulse import SeriesPulse
from usage.libraries.series_zone import SeriesZone
from usage.structures.app_exception import AppException
from usage.structures.sensor_breach import SensorBreach
from usage.structures.sensor_sample import SensorSample
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


class SensorCommand:
    """The house's thermometers: timestamped samples (temperatures) per house.

    Two things feed them and they meet here. Home Assistant posts a batch of
    current states every few minutes, signed with the house's sensor token; a
    house without Home Assistant has `SwitchBotSyncCommand` pull the same
    readings out of the cloud and hand them to `store` directly. The difference
    between the two is entirely in who worked out the instants a sample carries,
    which is settled before either of them gets here.

    An unknown entity becomes a sensor on the
    fly, named by the Home Assistant configuration or by the SwitchBot device;
    users rename, order and
    hide sensors in Settings (a hidden sensor keeps collecting, out of the
    graphs - a deleted one would only come back on the next push). A sample
    is keyed by the sensor and the instant its value last changed, so a value
    re-sent unchanged is a no-op rather than a duplicate. A push may also carry
    the charge of the thermometer that took the reading: that belongs to the
    sensor, not to the reading, so only the last one is kept.

    A sensor may carry an alert range (Settings, Sensors): when a push takes it
    out of that range, the users who opted in for the house get one email. The
    sensor remembers the side it is on, so the alert fires on the crossing, not
    on every push that follows it.
    """

    def __init__(self, database: Database, settings: Settings, email_sender: EmailSender) -> None:
        self._database = database
        self._settings = settings
        self._email_sender = email_sender

    def ingest(self, authorization: str, data: dict[str, Any]) -> dict[str, int]:
        house_id = IngestToken(self._database).house_id(authorization)
        samples = list(data.get("samples") or [])
        if len(samples) > Constants.ingest_max_samples:
            raise AppException(400, f"At most {Constants.ingest_max_samples} samples per request.")
        return self.store(house_id, [self._parse_sample(sample) for sample in samples])

    def store(self, house_id: int, parsed: list[SensorSample], create: bool = True) -> dict[str, int]:
        """Write a batch of samples, whichever of the three ways they reached the app.

        Home Assistant pushes them, the SwitchBot sync pulls them, and a
        SwitchBot webhook posts them as they happen. From here on the three are
        the same thing: the difference between them is entirely in who worked
        out `measured_at` and `reported_at`, and that is settled before anything
        arrives here.

        `create` is what keeps the webhook honest. A push and a pull are both
        answers to something this app asked for, so an entity nobody has seen
        before is a new thermometer. A webhook is not: it reports every device
        on the account, including another house's, and nothing signs it. So it
        may write to sensors that already exist and may not invent any.
        """
        known: dict[str, int] = {}
        created = 0
        accepted = 0
        with self._database.transaction():
            for sample in parsed:
                if sample.entity_id not in known:
                    found = self._find_sensor(house_id, sample) if not create else None
                    if not create and found is None:
                        continue
                    sensor_id, is_new = (found, False) if found is not None else self._find_or_create_sensor(house_id, sample)
                    known[sample.entity_id] = sensor_id
                    created += int(is_new)
                accepted += 1
                self._database.execute(
                    """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (known[sample.entity_id], sample.measured_at.isoformat(), sample.value),
                )
            self._store_batteries(parsed, known)
            self._store_reported(parsed, known)
            self._mark_push(house_id)
        # Outside the transaction: the samples are in whatever the mail relay does next.
        self._alert(house_id, parsed, known)
        return {"accepted": accepted, "created": created}

    def issue_token(self, user: SessionUser, house_id: int) -> dict[str, str]:
        """Mint the house's sensor token; the previous one stops working at once."""
        if not user.is_admin:
            raise AppException(403, "Only admins can do this.")
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        token = secrets.token_urlsafe(Constants.ingest_token_bytes)
        self._database.execute(
            "UPDATE houses SET ingest_token_hash = %s WHERE id = %s",
            (IngestToken.hashed(token), house_id),
        )
        return {"token": token}

    def list_sensors(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_house(user, house_id)
        latest = self._database.fetch_all(
            """
            SELECT DISTINCT ON (samples.sensor_id) samples.sensor_id, samples.measured_at, samples.value
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s
            ORDER BY samples.sensor_id, samples.measured_at DESC
            """,
            (house_id,),
        )
        sensors = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, entity_id_sealed AS entity_id, name_sealed AS name, unit, color, position, active,
                       threshold_min, threshold_max, battery, battery_at, reported_at
                FROM sensors WHERE house_id = %s ORDER BY position, id
                """,
                (house_id,),
            ),
            ("entity_id", "name"),
        )
        result: list[dict[str, Any]] = []
        for sensor in sensors:
            last = next((row for row in latest if int(row["sensor_id"]) == int(sensor["id"])), None)
            result.append(
                {
                    "id": int(sensor["id"]),
                    "entity_id": str(sensor["entity_id"]),
                    "name": str(sensor["name"]),
                    "unit": str(sensor["unit"]),
                    "color": str(sensor["color"] or ""),
                    "position": int(sensor["position"]),
                    "active": bool(sensor["active"]),
                    "last_value": float(last["value"]) if last is not None else None,
                    "last_at": last["measured_at"].isoformat() if last is not None else "",
                    "threshold_min": float(sensor["threshold_min"]) if sensor["threshold_min"] is not None else None,
                    "threshold_max": float(sensor["threshold_max"]) if sensor["threshold_max"] is not None else None,
                    "battery": int(sensor["battery"]) if sensor["battery"] is not None else None,
                    "battery_at": sensor["battery_at"].isoformat() if sensor["battery_at"] is not None else "",
                    "reported_at": sensor["reported_at"].isoformat() if sensor["reported_at"] is not None else "",
                },
            )
        return {"sensors": result}

    def update_sensor(self, user: SessionUser, sensor_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_sensor(user, sensor_id)
        name = str(data.get("name") or "").strip()
        if not name:
            raise AppException(400, "Enter a sensor name.")
        color = str(data.get("color") or "").strip().lower()
        if color and not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise AppException(400, "The colour must be like #2a78d6, or empty for the default.")
        # The alert range is in the thermometer's own unit; either side may stay open.
        threshold_min = self._threshold(data, "threshold_min")
        threshold_max = self._threshold(data, "threshold_max")
        if threshold_min is not None and threshold_max is not None and threshold_min >= threshold_max:
            raise AppException(400, "The alert minimum must be lower than the maximum.")
        # A range that moved re-arms the alert: the next push decides the state afresh.
        self._database.execute(
            """
            UPDATE sensors
            SET name_sealed = %s, unit = %s, color = %s, active = %s, threshold_min = %s, threshold_max = %s,
                alert_state = CASE
                    WHEN threshold_min IS DISTINCT FROM %s OR threshold_max IS DISTINCT FROM %s THEN %s
                    ELSE alert_state END
            WHERE id = %s
            """,
            (
                self._database.encrypt(name),
                str(data.get("unit") or "").strip(),
                color,
                bool(data.get("active")),
                threshold_min,
                threshold_max,
                threshold_min,
                threshold_max,
                Constants.alert_normal,
                sensor_id,
            ),
        )
        return {"message": "Sensor updated."}

    def set_order(self, user: SessionUser, data: dict[str, Any]) -> dict[str, str]:
        """The sensor order is shared by the house, unlike the personal meter order."""
        house_id = int(data.get("house_id") or 0)
        sensor_ids = [int(sensor_id) for sensor_id in data.get("sensor_ids") or []]
        self._require_house(user, house_id)
        rows = self._database.fetch_all("SELECT id FROM sensors WHERE house_id = %s ORDER BY id", (house_id,))
        if sorted(sensor_ids) != sorted(int(row["id"]) for row in rows):
            raise AppException(400, "The order must include every sensor of the house exactly once.")
        with self._database.transaction():
            for position, sensor_id in enumerate(sensor_ids):
                self._database.execute("UPDATE sensors SET position = %s WHERE id = %s", (position, sensor_id))
        return {"message": "Sensor order saved."}

    def series(
        self,
        user: SessionUser,
        house_id: int,
        days: int,
        previous: bool,
        offset: int,
        zone: str = "",
    ) -> dict[str, Any]:
        """Per active sensor, the samples of one `days`-long period averaged per time bucket.

        The period ends `offset` periods before now (0: the last `days`).
        With `previous`, the window doubles so the caller can overlay the
        period before (the buckets are day-aligned, so shifting by `days`
        lines them up).

        `zone` is the clock the buckets are cut on, so a day means midnight to
        midnight where the page is being read rather than on UTC, which is
        nobody's midnight. The house's own is the fallback and the answer says
        which was used, since a bucket cut on one clock and labelled on another
        would be worse than either.
        """
        self._require_house(user, house_id)
        zone = SeriesZone(self._database).of(zone, house_id)
        bucket_minutes = dict(Constants.sensor_ranges).get(days)
        if bucket_minutes is None:
            choices = ", ".join(str(range_days) for range_days, _ in Constants.sensor_ranges)
            raise AppException(400, f"The range must be one of {choices} days.")
        if offset < 0:
            raise AppException(400, "The offset counts periods back from now.")
        # One reading of the clock for the whole answer: the window's end and the
        # wait named beside it must not drift apart by the length of a query.
        now = datetime.now(UTC)
        until = now - timedelta(days=days * offset)
        since = until - timedelta(days=days * (2 if previous else 1))
        sensors = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, name_sealed AS name, unit, battery, battery_at, reported_at
                FROM sensors WHERE house_id = %s AND active ORDER BY position, id
                """,
                (house_id,),
            ),
            ("name",),
        )
        rows = self._database.fetch_all(
            """
            SELECT samples.sensor_id,
                   date_bin(%s, samples.measured_at AT TIME ZONE %s, TIMESTAMP '2000-01-01') AT TIME ZONE %s AS bucket,
                   AVG(samples.value) AS average, MIN(samples.value) AS low, MAX(samples.value) AS high
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active AND samples.measured_at >= %s AND samples.measured_at < %s
            GROUP BY samples.sensor_id, bucket
            ORDER BY samples.sensor_id, bucket
            """,
            (timedelta(minutes=bucket_minutes), zone, zone, house_id, since.isoformat(), until.isoformat()),
        )
        result: list[dict[str, Any]] = []
        for sensor in sensors:
            points = [
                {
                    "at": row["bucket"].isoformat(),
                    "average": round(float(row["average"]), 2),
                    "low": round(float(row["low"]), 2),
                    "high": round(float(row["high"]), 2),
                }
                for row in rows
                if int(row["sensor_id"]) == int(sensor["id"])
            ]
            if not points:
                continue
            result.append(
                {
                    "sensor_id": int(sensor["id"]),
                    "name": str(sensor["name"]),
                    "unit": str(sensor["unit"]),
                    "points": points,
                },
            )
        latest = self._latest(house_id, sensors)
        return {
            "days": days,
            "zone": zone,
            "bucket_minutes": bucket_minutes,
            "previous": previous,
            "offset": offset,
            "until": until.isoformat(),
            "series": result,
            # The tiles under the graph, which age between two pushes even when
            # the curves do not: they used to come from the sensor list, which
            # the view only re-asked for when it was entered, so a tile could
            # sit on an hour-old reading while the line beside it moved.
            "latest": latest,
            "stamp": SeriesPulse.stamp(result, latest),
            "next_poll_seconds": SeriesPulse.next_poll([self._due(house_id)], now),
        }

    def _latest(self, house_id: int, sensors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The freshest reading of each active sensor, and the charge that took it.

        A sensor quiet for the whole window has no curve but still has a tile,
        so this is asked of the whole history rather than of the period on show.
        """
        rows = self._database.fetch_all(
            """
            SELECT DISTINCT ON (samples.sensor_id) samples.sensor_id, samples.measured_at, samples.value
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active
            ORDER BY samples.sensor_id, samples.measured_at DESC
            """,
            (house_id,),
        )
        result: list[dict[str, Any]] = []
        for sensor in sensors:
            row = next((item for item in rows if int(item["sensor_id"]) == int(sensor["id"])), None)
            if row is None:
                continue
            result.append(
                {
                    "sensor_id": int(sensor["id"]),
                    "value": float(row["value"]),
                    "at": row["measured_at"].isoformat(),
                    "battery": int(sensor["battery"]) if sensor["battery"] is not None else None,
                    "battery_at": sensor["battery_at"].isoformat() if sensor["battery_at"] is not None else "",
                    # What the tile's "ago" counts from: when the thermometer was
                    # last heard from, not when its reading last happened to move.
                    "reported_at": sensor["reported_at"].isoformat() if sensor["reported_at"] is not None else "",
                },
            )
        return result

    def _due(self, house_id: int) -> datetime | None:
        """When Home Assistant is next expected to push, going by the last two.

        Before two have been seen there is nothing to measure, so the house
        falls back to the assumed cadence counted from the moment it was last
        heard from. A house that has never pushed at all answers nothing, and
        is then looked in on at the ceiling: there is no cadence to guess, and
        the first push could as easily be tomorrow as in a minute.
        """
        row = self._database.fetch_one(
            "SELECT sensors_pushed_at, sensors_push_seconds FROM houses WHERE id = %s",
            (house_id,),
        )
        if row is None or row["sensors_pushed_at"] is None:
            return None
        pushed: datetime = row["sensors_pushed_at"]
        cadence = row["sensors_push_seconds"] or Constants.realtime_push_default_seconds
        return pushed + timedelta(seconds=int(cadence))

    def alerts(self, user: SessionUser, house_id: int) -> dict[str, bool]:
        """Whether this user asked for the house's threshold alerts (off unless asked)."""
        self._require_house(user, house_id)
        row = self._database.fetch_one(
            "SELECT enabled FROM sensor_alerts WHERE user_id = %s AND house_id = %s",
            (user.user_id, house_id),
        )
        return {"enabled": row is not None and bool(row["enabled"])}

    def set_alerts(self, user: SessionUser, data: dict[str, Any]) -> dict[str, str]:
        house_id = int(data.get("house_id") or 0)
        enabled = bool(data.get("enabled"))
        self._require_house(user, house_id)
        self._database.execute(
            """
            INSERT INTO sensor_alerts(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            (user.user_id, house_id, enabled),
        )
        result = "Threshold alerts enabled for this house." if enabled else "Threshold alerts disabled for this house."
        return {"message": result}

    def _find_sensor(self, house_id: int, sample: SensorSample) -> int | None:
        """This house's sensor for that entity, and never one belonging to another."""
        row = self._database.fetch_one(
            "SELECT id FROM sensors WHERE house_id = %s AND entity_hash = %s",
            (house_id, self._database.blind_index(sample.entity_id)),
        )
        return None if row is None else int(row["id"])

    def _find_or_create_sensor(self, house_id: int, sample: SensorSample) -> tuple[int, bool]:
        entity_hash = self._database.blind_index(sample.entity_id)
        row = self._database.fetch_one(
            "SELECT id FROM sensors WHERE house_id = %s AND entity_hash = %s",
            (house_id, entity_hash),
        )
        if row is not None:
            return int(row["id"]), False
        count = self._database.fetch_one("SELECT COUNT(*) AS count FROM sensors WHERE house_id = %s", (house_id,))
        sensor_id = self._database.execute(
            """
            INSERT INTO sensors(house_id, entity_id_sealed, entity_hash, name_sealed, unit, position, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                self._database.encrypt(sample.entity_id),
                entity_hash,
                self._database.encrypt(sample.name),
                sample.unit,
                int(count["count"]) if count is not None else 0,
                # Only ever on the way in: a sensor that already exists is shown
                # or hidden by whoever decided that in Settings, and no arriving
                # sample is allowed to overrule them.
                not sample.hidden,
            ),
        )
        return sensor_id, True

    def _mark_push(self, house_id: int) -> None:
        """When this push landed, and how long it had been since the one before.

        A sample is stamped with the instant its value last changed, which is
        the thermometer's clock and says nothing about when Home Assistant
        chose to send it: a room that has held 19.4 all afternoon carries an
        afternoon-old stamp. So the arrival is written down here instead, and
        the gap between two arrivals is the cadence the Realtime page is told
        to wait. A gap longer than the ceiling is an outage rather than a
        cadence and is not allowed to teach the page to sleep through the day.
        """
        self._database.execute(
            """
            UPDATE houses
            SET sensors_push_seconds = CASE
                    WHEN sensors_pushed_at IS NULL THEN sensors_push_seconds
                    ELSE LEAST(%s, GREATEST(1, EXTRACT(EPOCH FROM (now() - sensors_pushed_at))::int))
                END,
                sensors_pushed_at = now()
            WHERE id = %s
            """,
            (Constants.realtime_push_max_seconds, house_id),
        )

    def _store_batteries(self, parsed: list[SensorSample], known: dict[str, int]) -> None:
        """Keep the last charge each thermometer reported; only the current one is shown."""
        charges: dict[int, SensorSample] = {}
        for sample in parsed:
            sensor_id = known.get(sample.entity_id)
            if sensor_id is None or sample.battery is None:
                continue
            known_sample = charges.get(sensor_id)
            if known_sample is None or sample.measured_at >= known_sample.measured_at:
                charges[sensor_id] = sample
        for sensor_id, sample in charges.items():
            # Never backwards. Three things write here now, and a webhook event
            # can arrive after a poll that already reported a later reading.
            self._database.execute(
                """
                UPDATE sensors SET battery = %s, battery_at = %s
                WHERE id = %s AND (battery_at IS NULL OR battery_at <= %s)
                """,
                (sample.battery, sample.measured_at.isoformat(), sensor_id, sample.measured_at.isoformat()),
            )

    def _store_reported(self, parsed: list[SensorSample], known: dict[str, int]) -> None:
        """Keep when each thermometer was last heard from; only the latest is shown.

        Kept apart from the charge on purpose. A push carries a battery only for
        a thermometer that has one, and a reported instant only once the Home
        Assistant template sends it, so neither may blank the other.
        """
        heard: dict[int, datetime] = {}
        for sample in parsed:
            sensor_id = known.get(sample.entity_id)
            if sensor_id is None or sample.reported_at is None:
                continue
            if sensor_id not in heard or sample.reported_at >= heard[sensor_id]:
                heard[sensor_id] = sample.reported_at
        for sensor_id, reported_at in heard.items():
            # Never backwards, for the same reason: a late event would otherwise
            # make a thermometer look as though it had not been heard from since.
            self._database.execute(
                """
                UPDATE sensors SET reported_at = %s
                WHERE id = %s AND (reported_at IS NULL OR reported_at < %s)
                """,
                (reported_at.isoformat(), sensor_id, reported_at.isoformat()),
            )

    def _parse_sample(self, data: dict[str, Any]) -> SensorSample:
        entity_id = str(data.get("entity_id") or "").strip().lower()
        if not entity_id:
            raise AppException(400, "Each sample needs an entity_id.")
        try:
            value = float(data.get("value") or 0.0)
        except (TypeError, ValueError):
            raise AppException(400, f"The value of {entity_id} is not a number.") from None
        if not math.isfinite(value):
            raise AppException(400, f"The value of {entity_id} is not a number.")
        return SensorSample(
            entity_id=entity_id,
            name=str(data.get("name") or entity_id).strip(),
            unit=str(data.get("unit") or "").strip(),
            value=round(value, 2),
            measured_at=self._parse_instant(str(data.get("measured_at") or "")),
            battery=self._parse_battery(data.get("battery"), entity_id),
            # Absent from a push written before this field existed, and then
            # left unknown: standing in the push's own arrival would claim a
            # freshness the thermometer has not vouched for, which is the very
            # thing this column is here to answer.
            reported_at=self._parse_optional_instant(str(data.get("reported_at") or "")),
        )

    def _parse_battery(self, raw: Any, entity_id: str) -> int | None:
        """The thermometer's own charge, as a whole percentage; absent for a mains-fed one."""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            charge = round(float(raw))
        except (TypeError, ValueError):
            raise AppException(400, f"The battery of {entity_id} is not a number.") from None
        if not 0 <= charge <= 100:
            raise AppException(400, f"The battery of {entity_id} is not a percentage.")
        return charge

    @classmethod
    def _parse_optional_instant(cls, text: str) -> datetime | None:
        """An instant a push may simply not carry, as against one it may leave to us."""
        return cls._parse_instant(text) if text.strip() else None

    @classmethod
    def _parse_instant(cls, text: str) -> datetime:
        if not text.strip():
            return datetime.now(UTC)
        try:
            result = datetime.fromisoformat(text.strip())
        except ValueError:
            raise AppException(400, f"The instant {text} is not an ISO 8601 date and time.") from None
        if result.tzinfo is None:
            result = result.replace(tzinfo=UTC)
        return result

    def _visible_house_ids(self, user: SessionUser) -> list[int]:
        # Everyone, admins included, only sees the houses they are linked to.
        rows = self._database.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (user.user_id,))
        return [int(row["house_id"]) for row in rows]

    def _require_house(self, user: SessionUser, house_id: int) -> None:
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        if house_id not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")

    def _require_sensor(self, user: SessionUser, sensor_id: int) -> dict[str, Any]:
        result = self._database.fetch_one("SELECT id, house_id FROM sensors WHERE id = %s", (sensor_id,))
        if result is None:
            raise AppException(404, "The sensor was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result

    def _threshold(self, data: dict[str, Any], key: str) -> float | None:
        raw = data.get(key)
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return round(float(raw), 2)
        except (TypeError, ValueError):
            raise AppException(400, "The alert minimum and maximum must be numbers.") from None

    def _alert(self, house_id: int, parsed: list[SensorSample], known: dict[str, int]) -> None:
        """Email the house's subscribers about the thermometers that just left their range.

        Edge triggered: Home Assistant pushes every few minutes, so the crossing
        is worth an email, not every sample that stays out of range afterwards.
        """
        breaches = self._breaches(parsed, known)
        if breaches:
            self._send_alerts(house_id, breaches)

    def _breaches(self, parsed: list[SensorSample], known: dict[str, int]) -> list[SensorBreach]:
        """The sensors of this push whose state changed, with the stored state brought up to date."""
        sensor_ids = sorted(set(known.values()))
        if not sensor_ids:
            return []
        sensors = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, name_sealed AS name, unit, threshold_min, threshold_max, alert_state
                FROM sensors
                WHERE id = ANY(%s) AND (threshold_min IS NOT NULL OR threshold_max IS NOT NULL)
                ORDER BY position, id
                """,
                (sensor_ids,),
            ),
            ("name",),
        )
        result: list[SensorBreach] = []
        for sensor in sensors:
            sensor_id = int(sensor["id"])
            last = self._last_sample(sensor_id, parsed, known)
            if last is None:
                continue
            state, threshold = self._state_of(last.value, sensor)
            if state == str(sensor["alert_state"]):
                continue
            self._database.execute("UPDATE sensors SET alert_state = %s WHERE id = %s", (state, sensor_id))
            if state != Constants.alert_normal:
                result.append(
                    SensorBreach(
                        sensor_id=sensor_id,
                        name=str(sensor["name"]),
                        value=last.value,
                        unit=str(sensor["unit"]),
                        state=state,
                        threshold=threshold,
                    ),
                )
        return result

    def _last_sample(self, sensor_id: int, parsed: list[SensorSample], known: dict[str, int]) -> SensorSample | None:
        # One push can carry several samples of the same thermometer: the latest one decides.
        samples = [sample for sample in parsed if known.get(sample.entity_id) == sensor_id]
        return max(samples, key=lambda sample: sample.measured_at, default=None)

    def _state_of(self, value: float, sensor: dict[str, Any]) -> tuple[str, float]:
        minimum = sensor["threshold_min"]
        maximum = sensor["threshold_max"]
        if minimum is not None and value < float(minimum):
            return Constants.alert_below, float(minimum)
        if maximum is not None and value > float(maximum):
            return Constants.alert_above, float(maximum)
        return Constants.alert_normal, 0.0

    def _send_alerts(self, house_id: int, breaches: list[SensorBreach]) -> None:
        recipients = self._database.fetch_all(
            """
            SELECT users.email_sealed AS email
            FROM sensor_alerts
            JOIN users ON users.id = sensor_alerts.user_id
            JOIN user_houses ON user_houses.user_id = sensor_alerts.user_id
                            AND user_houses.house_id = sensor_alerts.house_id
            WHERE sensor_alerts.house_id = %s AND sensor_alerts.enabled
            ORDER BY sensor_alerts.user_id
            """,
            (house_id,),
        )
        if not recipients:
            return
        house = self._database.fetch_one("SELECT name_sealed AS name FROM houses WHERE id = %s", (house_id,))
        house_name = self._database.decrypt(str(house["name"])) if house is not None else ""
        subject, body_lines = EmailTexts.sensor_alert(house_name, breaches, self._settings.base_url or "")
        for recipient in recipients:
            email = self._database.decrypt(str(recipient["email"]))
            if not self._email_sender.send(email, subject, body_lines):
                logging.getLogger("usage").warning("[ALERT] email failed for %s of house %s", email, house_id)
