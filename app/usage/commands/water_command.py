from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.eye_on_water_client import EyeOnWaterClient
from usage.libraries.series_pulse import SeriesPulse
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser
from usage.structures.water_meter import WaterMeter


class WaterCommand:
    """The EyeOnWater feeds of a house, and the consumption they have collected.

    A house whose water never stops for a whole day is leaking, and the users who
    asked for it get one email when that starts - the alert is the house's, like
    the thermometers' one, not any single meter's. A meter may also carry a limit
    on what it draws in a rolling 24 hours; moving that limit re-arms the alert,
    since the flag standing against it was the verdict on the old number.

    A feed is one meter of one EyeOnWater account. The meter uuid is asked of
    the account rather than copied by hand: the portal shows a nineteen-digit
    uuid beside a nine-digit meter id, and an export for the wrong one dies
    inside EyeOnWater's own task with "list index out of range". An account
    with a single meter needs no uuid at all.

    Creating a feed also asks for a day of readings straight away, so a wrong
    password is refused in the form rather than discovered hours later by the
    background sync.

    Everything is stored in cubic metres, and the graph sums rather than
    averages: water is a counter, not a temperature.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def list_feeds(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_admin(user)
        self._require_house(user, house_id)
        feeds = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, hostname, username_sealed AS username, meter_uuid_sealed AS meter_uuid, export_unit,
                       active, last_sync_at, last_point_at, last_error, backfill_from, backfill_done, daily_max
                FROM water_feeds WHERE house_id = %s ORDER BY id
                """,
                (house_id,),
            ),
            ("username", "meter_uuid"),
        )
        result: list[dict[str, Any]] = []
        for feed in feeds:
            counts = self._database.fetch_one(
                "SELECT COUNT(*) AS points, MIN(measured_at) AS first_at FROM water_points WHERE feed_id = %s",
                (int(feed["id"]),),
            )
            result.append(
                {
                    "id": int(feed["id"]),
                    "hostname": str(feed["hostname"]),
                    "username": str(feed["username"]),
                    "meter_uuid": str(feed["meter_uuid"]),
                    "export_unit": str(feed["export_unit"]),
                    "active": bool(feed["active"]),
                    "last_sync_at": self._moment(feed["last_sync_at"]),
                    "last_point_at": self._moment(feed["last_point_at"]),
                    "last_error": str(feed["last_error"]),
                    "backfill_from": str(feed["backfill_from"] or ""),
                    "backfill_done": bool(feed["backfill_done"]),
                    "daily_max": None if feed["daily_max"] is None else float(feed["daily_max"]),
                    "points": int(counts["points"]) if counts is not None else 0,
                    "first_point_at": self._moment(counts["first_at"]) if counts is not None else "",
                },
            )
        return {"feeds": result}

    def create_feed(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        house_id = int(data.get("house_id") or 0)
        self._require_admin(user)
        self._require_house(user, house_id)
        hostname = self._hostname(data)
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        meter_uuid = self._meter_uuid(data)
        if not username or not password:
            raise AppException(400, "Enter the EyeOnWater username and password.")
        export_unit = str(data.get("export_unit") or Constants.water_export_unit).strip() or Constants.water_export_unit
        # Proves the credentials, settles the uuid, and reads a day back.
        client = EyeOnWaterClient(hostname, username, password, export_unit)
        meter_uuid = self._resolve_meter(client, meter_uuid)
        self._probe(client, meter_uuid)
        existing = self._database.fetch_one(
            "SELECT id FROM water_feeds WHERE house_id = %s AND meter_uuid_hash = %s",
            (house_id, self._database.blind_index(meter_uuid)),
        )
        if existing is not None:
            raise AppException(409, "This meter is already collected for this house.")
        feed_id = self._database.execute(
            """
            INSERT INTO water_feeds(house_id, hostname, username_sealed, username_hash, password_sealed,
                                    meter_uuid_sealed, meter_uuid_hash, export_unit, daily_max)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                hostname,
                self._database.encrypt(username),
                self._database.blind_index(username),
                self._database.encrypt(password),
                self._database.encrypt(meter_uuid),
                self._database.blind_index(meter_uuid),
                export_unit,
                self._daily_max(data),
            ),
        )
        return {"id": feed_id, "message": "Water feed added. The first import starts within a minute."}

    def update_feed(self, user: SessionUser, feed_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        feed = self._require_feed(user, feed_id)
        hostname = self._hostname(data)
        username = str(data.get("username") or "").strip()
        meter_uuid = self._meter_uuid(data)
        if not username:
            raise AppException(400, "Enter the EyeOnWater username.")
        # An empty password means "keep the one already stored".
        password = str(data.get("password") or "") or self._database.decrypt(str(feed["password"]))
        export_unit = str(data.get("export_unit") or Constants.water_export_unit).strip() or Constants.water_export_unit
        daily_max = self._daily_max(data)
        client = EyeOnWaterClient(hostname, username, password, export_unit)
        meter_uuid = self._resolve_meter(client, meter_uuid)
        self._probe(client, meter_uuid)
        self._database.execute(
            """
            UPDATE water_feeds
            SET hostname = %s, username_sealed = %s, username_hash = %s, password_sealed = %s,
                meter_uuid_sealed = %s, meter_uuid_hash = %s, export_unit = %s, active = %s,
                daily_max = %s, last_error = '',
                over_daily = CASE WHEN daily_max IS DISTINCT FROM %s THEN false ELSE over_daily END
            WHERE id = %s
            """,
            (
                hostname,
                self._database.encrypt(username),
                self._database.blind_index(username),
                self._database.encrypt(password),
                self._database.encrypt(meter_uuid),
                self._database.blind_index(meter_uuid),
                export_unit,
                bool(data.get("active")),
                daily_max,
                # A limit that moved re-arms the alert, exactly as a thermometer's
                # range does: the stored flag was the verdict on the old number,
                # and leaving it would keep the graph red until the next pull.
                daily_max,
                feed_id,
            ),
        )
        return {"message": "Water feed updated."}

    def delete_feed(self, user: SessionUser, feed_id: int) -> dict[str, str]:
        self._require_admin(user)
        self._require_feed(user, feed_id)
        self._database.execute("DELETE FROM water_feeds WHERE id = %s", (feed_id,))
        return {"message": "Water feed deleted, with everything it had collected."}

    def restart_backfill(self, user: SessionUser, feed_id: int) -> dict[str, str]:
        """Send the history walk back to the start; stored points are kept and refreshed."""
        self._require_admin(user)
        self._require_feed(user, feed_id)
        # last_sync_at goes with it: the feed becomes due again, so the walk
        # starts within the minute rather than whenever the quarter hour lands.
        self._database.execute(
            """
            UPDATE water_feeds
            SET backfill_from = NULL, backfill_done = false, empty_chunks = 0, last_sync_at = NULL
            WHERE id = %s
            """,
            (feed_id,),
        )
        return {"message": "History import restarted. It starts within a minute and walks back a month at a time."}

    def series(self, user: SessionUser, house_id: int, days: int, previous: bool, offset: int) -> dict[str, Any]:
        """The house's consumption over one `days`-long period, summed per bucket.

        Same windowing as the thermometers so both graphs of the Realtime view
        move together, but the buckets are sums: half a bucket of water is not
        an average of anything.
        """
        self._require_house(user, house_id)
        bucket_minutes = dict(Constants.water_ranges).get(days)
        if bucket_minutes is None:
            choices = ", ".join(str(range_days) for range_days, _ in Constants.water_ranges)
            raise AppException(400, f"The range must be one of {choices} days.")
        if offset < 0:
            raise AppException(400, "The offset counts periods back from now.")
        # One reading of the clock for the whole answer: the window's end and the
        # wait named beside it must not drift apart by the length of a query.
        now = datetime.now(UTC)
        until = now - timedelta(days=days * offset)
        since = until - timedelta(days=days * (2 if previous else 1))
        rows = self._database.fetch_all(
            """
            SELECT date_bin(%s, water_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(water_points.volume) AS volume
            FROM water_points JOIN water_feeds ON water_feeds.id = water_points.feed_id
            WHERE water_feeds.house_id = %s AND water_feeds.active
              AND water_points.measured_at >= %s AND water_points.measured_at < %s
            GROUP BY bucket ORDER BY bucket
            """,
            (timedelta(minutes=bucket_minutes), house_id, since.isoformat(), until.isoformat()),
        )
        points = [{"at": row["bucket"].isoformat(), "volume": round(float(row["volume"]), 4)} for row in rows]
        latest = self._latest(house_id)
        alert = self._alert(house_id)
        return {
            "days": days,
            "bucket_minutes": bucket_minutes,
            "previous": previous,
            "offset": offset,
            "until": until.isoformat(),
            "unit": "m³",
            "points": points,
            "latest": latest,
            "alert": alert,
            "stamp": SeriesPulse.stamp(points, latest, alert),
            "next_poll_seconds": SeriesPulse.next_poll([self._due(house_id)], now),
        }

    def _due(self, house_id: int) -> datetime | None:
        """When the earliest of this house's meters is next pulled.

        A water bar cannot move between two syncs: the rows only arrive when
        the loop signs into the portal and asks for an export, so there is
        nothing for the page to see in the meantime. The tick is added because
        the loop wakes on its own clock rather than at the instant a feed comes
        due, and arriving a second early would only cost a wasted request.

        A feed that has never synced is due now.
        """
        row = self._database.fetch_one(
            """
            SELECT MIN(COALESCE(last_sync_at + %s, now())) AS due
            FROM water_feeds WHERE house_id = %s AND active
            """,
            (timedelta(seconds=Constants.water_sync_seconds + Constants.water_tick_seconds), house_id),
        )
        if row is None:
            return None
        due: datetime | None = row["due"]
        return due

    def alerts(self, user: SessionUser, house_id: int) -> dict[str, bool]:
        """Whether this user asked for the house's leak alerts (off unless asked)."""
        self._require_house(user, house_id)
        row = self._database.fetch_one(
            "SELECT enabled FROM water_alerts WHERE user_id = %s AND house_id = %s",
            (user.user_id, house_id),
        )
        return {"enabled": row is not None and bool(row["enabled"])}

    def set_alerts(self, user: SessionUser, data: dict[str, Any]) -> dict[str, str]:
        house_id = int(data.get("house_id") or 0)
        enabled = bool(data.get("enabled"))
        self._require_house(user, house_id)
        self._database.execute(
            """
            INSERT INTO water_alerts(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            (user.user_id, house_id, enabled),
        )
        result = "Leak alerts enabled for this house." if enabled else "Leak alerts disabled for this house."
        return {"message": result}

    def _alert(self, house_id: int) -> dict[str, Any]:
        """The house's daily limit, and whether it is over it right now.

        Summed across the active meters, because the limit belongs to a meter
        and the graph is the house: two meters with a limit each make one number
        the whole house is measured against. A house where nobody set one gets
        no number at all rather than a zero, which would read as a limit of none.
        """
        row = self._database.fetch_one(
            """
            SELECT SUM(daily_max) AS daily_max, BOOL_OR(over_daily) AS over
            FROM water_feeds WHERE house_id = %s AND active
            """,
            (house_id,),
        )
        if row is None or row["daily_max"] is None:
            return {"daily_max": None, "over": False}
        return {"daily_max": round(float(row["daily_max"]), 4), "over": bool(row["over"])}

    def _latest(self, house_id: int) -> dict[str, Any]:
        row = self._database.fetch_one(
            """
            SELECT water_points.measured_at, water_points.volume, water_points.reading
            FROM water_points JOIN water_feeds ON water_feeds.id = water_points.feed_id
            WHERE water_feeds.house_id = %s AND water_feeds.active
            ORDER BY water_points.measured_at DESC LIMIT 1
            """,
            (house_id,),
        )
        if row is None:
            return {"at": "", "volume": None, "reading": None}
        return {
            "at": self._moment(row["measured_at"]),
            "volume": round(float(row["volume"]), 4),
            "reading": None if row["reading"] is None else round(float(row["reading"]), 4),
        }

    def _resolve_meter(self, client: EyeOnWaterClient, wanted: str) -> str:
        """The uuid to collect, checked against the ones the account actually has."""
        meters = client.meters()
        if not meters:
            raise AppException(502, "That EyeOnWater account has no meter on it.")
        known = [meter.uuid for meter in meters]
        if not wanted:
            if len(known) > 1:
                raise AppException(400, f"This account has several meters. Enter one of these uuids: {', '.join(known)}.")
            return known[0]
        if wanted not in known:
            raise AppException(400, self._wrong_meter(wanted, meters))
        return wanted

    @classmethod
    def _wrong_meter(cls, wanted: str, meters: list[WaterMeter]) -> str:
        """Name the right uuid, and say so plainly when the meter id was used."""
        mistaken = next((meter for meter in meters if meter.meter_id == wanted), None)
        if mistaken is not None:
            return f"That is the meter ID, not the meter uuid. This meter's uuid is {mistaken.uuid}."
        return f"This account has no meter with that uuid. It has: {', '.join(meter.uuid for meter in meters)}."

    def _probe(self, client: EyeOnWaterClient, meter_uuid: str) -> None:
        """One day of export, thrown away: it is the account that is being tested."""
        today = datetime.now(UTC).date()
        client.export(meter_uuid, today - timedelta(days=Constants.water_recent_days), today)

    @classmethod
    def _daily_max(cls, data: dict[str, Any]) -> float | None:
        """The most this meter may draw in a rolling 24 hours, in cubic metres.

        Empty is the ordinary case and means no alert at all: a limit nobody
        chose is not a limit worth mailing about. Zero would alert on every
        reading for ever, which is why it is refused rather than stored.
        """
        raw = data.get("daily_max")
        if raw is None or str(raw).strip() == "":
            return None
        try:
            result = float(raw)
        except (TypeError, ValueError):
            raise AppException(400, "The daily limit must be a number.") from None
        if result <= 0:
            raise AppException(400, "The daily limit must be more than zero, or empty for no alert.")
        return round(result, 6)

    @classmethod
    def _hostname(cls, data: dict[str, Any]) -> str:
        result = str(data.get("hostname") or Constants.water_host_default).strip().lower()
        if result not in Constants.water_hosts:
            choices = " or ".join(Constants.water_hosts)
            raise AppException(400, f"The EyeOnWater host must be {choices}.")
        return result

    @classmethod
    def _meter_uuid(cls, data: dict[str, Any]) -> str:
        """Empty is allowed: the account is asked, and one meter needs no choosing."""
        result = str(data.get("meter_uuid") or "").strip()
        if result and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", result):
            raise AppException(400, "A meter uuid is letters and digits only.")
        return result

    @classmethod
    def _moment(cls, value: datetime | None) -> str:
        return value.isoformat() if value is not None else ""

    def _visible_house_ids(self, user: SessionUser) -> list[int]:
        rows = self._database.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (user.user_id,))
        return [int(row["house_id"]) for row in rows]

    @classmethod
    def _require_admin(cls, user: SessionUser) -> None:
        if not user.is_admin:
            raise AppException(403, "Only admins can do this.")

    def _require_house(self, user: SessionUser, house_id: int) -> None:
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        if house_id not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")

    def _require_feed(self, user: SessionUser, feed_id: int) -> dict[str, Any]:
        result = self._database.fetch_one(
            "SELECT id, house_id, password_sealed AS password FROM water_feeds WHERE id = %s",
            (feed_id,),
        )
        if result is None:
            raise AppException(404, "The water feed was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result
