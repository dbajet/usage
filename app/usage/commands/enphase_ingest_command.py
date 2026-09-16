from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.ingest_token import IngestToken
from usage.structures.app_exception import AppException
from usage.structures.enphase_live import EnphaseLive
from usage.structures.enphase_point import EnphasePoint


class EnphaseIngestCommand:
    """Solar pushed by Home Assistant, straight off the gateway on the house's network.

    The cloud API owns the years and is metered; this owns the last minute and
    is free. A gateway only answers on its own LAN and this app runs on a VPS,
    so the push is the only way round - the same way the thermometers arrive,
    on the same house token.

    What a push carries is readings, not rates: the gateway's lifetime counters
    in watt-hours, and the app differences two consecutive ones to get the
    energy of the interval between them. That is the same trick the rest of the
    app uses on a meter reading, and it is what makes a missed push cost
    nothing - the next one simply spans a longer interval and the total still
    comes out right. Trusting a reported rate instead would turn every dropped
    push into a hole.

    Two things it refuses to draw. A counter that has gone backwards is a
    gateway that was replaced or reset, not a house that generated negative
    electricity, so it starts a fresh baseline and draws nothing. And a gap
    longer than an hour is an outage rather than an interval: charting it would
    put one enormous bar where a quiet night belongs.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def ingest(self, authorization: str, data: dict[str, Any]) -> dict[str, Any]:
        house_id = IngestToken(self._database).house_id(authorization)
        push = self._push(house_id, data)
        with self._database.transaction():
            previous = self._previous(house_id)
            self._remember(push)
            point = self._interval(previous, push)
            if point is not None:
                self._store(self._local_feed(house_id), point)
        return {"accepted": True, "stored": point is not None}

    def _push(self, house_id: int, data: dict[str, Any]) -> EnphaseLive:
        moment = self._moment(str(data.get("measured_at") or ""))
        result = EnphaseLive(
            house_id=house_id,
            measured_at=moment,
            production_power=self._converted(data, "production_power", Constants.enphase_power_watts),
            consumption_power=self._converted(data, "consumption_power", Constants.enphase_power_watts),
            battery_level=self._percent(data.get("battery_level")),
            production_lifetime=self._converted(data, "production_lifetime", Constants.enphase_energy_watt_hours),
            consumption_lifetime=self._converted(data, "consumption_lifetime", Constants.enphase_energy_watt_hours),
        )
        if not any(
            value is not None
            for value in (
                result.production_power,
                result.consumption_power,
                result.battery_level,
                result.production_lifetime,
                result.consumption_lifetime,
            )
        ):
            raise AppException(400, "The push carried no reading at all.")
        return result

    def _previous(self, house_id: int) -> EnphaseLive | None:
        row = self._database.fetch_one(
            """
            SELECT house_id, measured_at, production_power, consumption_power, battery_level,
                   production_lifetime, consumption_lifetime
            FROM enphase_live WHERE house_id = %s
            """,
            (house_id,),
        )
        if row is None:
            return None
        return EnphaseLive(
            house_id=int(row["house_id"]),
            measured_at=row["measured_at"],
            production_power=self._number(row["production_power"]),
            consumption_power=self._number(row["consumption_power"]),
            battery_level=self._number(row["battery_level"]),
            production_lifetime=self._number(row["production_lifetime"]),
            consumption_lifetime=self._number(row["consumption_lifetime"]),
        )

    def _remember(self, push: EnphaseLive) -> None:
        """The newest push, which is both the tiles and the next interval's baseline."""
        self._database.execute(
            """
            INSERT INTO enphase_live(house_id, measured_at, production_power, consumption_power,
                                     battery_level, production_lifetime, consumption_lifetime, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (house_id) DO UPDATE
            SET measured_at = EXCLUDED.measured_at,
                production_power = EXCLUDED.production_power,
                consumption_power = EXCLUDED.consumption_power,
                battery_level = EXCLUDED.battery_level,
                production_lifetime = EXCLUDED.production_lifetime,
                consumption_lifetime = EXCLUDED.consumption_lifetime,
                updated_at = now()
            """,
            (
                push.house_id,
                push.measured_at.isoformat(),
                push.production_power,
                push.consumption_power,
                push.battery_level,
                push.production_lifetime,
                push.consumption_lifetime,
            ),
        )

    @classmethod
    def _interval(cls, previous: EnphaseLive | None, push: EnphaseLive) -> EnphasePoint | None:
        """The energy between two readings, labelled by when that interval started."""
        if previous is None:
            return None
        seconds = (push.measured_at - previous.measured_at).total_seconds()
        if seconds < Constants.enphase_push_min_gap_seconds:
            # The same push again, or two inside a second: nothing happened between them.
            return None
        if seconds > Constants.enphase_push_max_gap_minutes * 60:
            # An outage, not an interval. The baseline has already been moved on,
            # so the next push measures from here and only this gap is lost.
            return None
        production = cls._consumed(previous.production_lifetime, push.production_lifetime)
        consumption = cls._consumed(previous.consumption_lifetime, push.consumption_lifetime)
        if production is None and consumption is None and push.battery_level is None:
            return None
        return EnphasePoint(
            measured_at=previous.measured_at,
            span_minutes=max(1, round(seconds / 60)),
            production=production,
            consumption=consumption,
            battery_level=push.battery_level,
        )

    @classmethod
    def _consumed(cls, before: float | None, after: float | None) -> float | None:
        """Watt-hours between two lifetime readings, in kilowatt-hours."""
        if before is None or after is None:
            return None
        if after < before:
            # The counter went backwards: a replaced or reset gateway. The new
            # reading is the baseline from here; this interval is not a number.
            return None
        return round((after - before) / Constants.enphase_watt_hours_per_kwh, 6)

    def _store(self, feed_id: int, point: EnphasePoint) -> None:
        """A push is complete in itself, so it overwrites rather than merges.

        The cloud sync's three streams arrive in three calls and have to fill in
        each other's blanks; one push carries every field it is ever going to.
        """
        self._database.execute(
            """
            INSERT INTO enphase_points(feed_id, measured_at, span_minutes, production, consumption, battery_level)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (feed_id, measured_at, span_minutes) DO UPDATE
            SET production = EXCLUDED.production,
                consumption = EXCLUDED.consumption,
                battery_level = EXCLUDED.battery_level
            """,
            (
                feed_id,
                point.measured_at.isoformat(),
                point.span_minutes,
                point.production,
                point.consumption,
                point.battery_level,
            ),
        )

    def _local_feed(self, house_id: int) -> int:
        """The house's local feed, made on the first push that needs one."""
        system_id = Constants.enphase_local_system_id
        row = self._database.fetch_one(
            "SELECT id FROM enphase_feeds WHERE house_id = %s AND source = %s",
            (house_id, Constants.enphase_source_local),
        )
        if row is not None:
            return int(row["id"])
        return self._database.execute(
            """
            INSERT INTO enphase_feeds(house_id, client_id_sealed, client_secret_sealed, api_key_sealed,
                                      system_id_sealed, system_id_hash, source)
            VALUES (%s, '', '', '', %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                self._database.encrypt(system_id),
                self._database.blind_index(system_id),
                Constants.enphase_source_local,
            ),
        )

    @classmethod
    def _moment(cls, raw: str) -> datetime:
        """When the gateway was read; empty means the push is about now."""
        text = raw.strip()
        if not text:
            return datetime.now(UTC)
        try:
            result = datetime.fromisoformat(text)
        except ValueError:
            raise AppException(400, "The push carried an unreadable instant.") from None
        return result if result.tzinfo is not None else result.replace(tzinfo=UTC)

    @classmethod
    def _converted(cls, data: dict[str, Any], field: str, factors: tuple[tuple[str, float], ...]) -> float | None:
        """One reading, brought into watts or watt-hours from whatever it arrived in.

        An empty unit is the base one, which is what the field is named for. A
        unit nobody here recognises is no reading at all rather than a number
        that is wrong by three orders of magnitude and looks entirely plausible.
        """
        value = cls._number(data.get(field))
        if value is None:
            return None
        unit = str(data.get(f"{field}_unit") or "").strip().upper()
        if not unit:
            return value
        factor = dict(factors).get(unit)
        if factor is None:
            return None
        return round(value * factor, 6)

    @classmethod
    def _percent(cls, raw: Any) -> float | None:
        result = cls._number(raw)
        if result is None:
            return None
        return round(max(0.0, min(Constants.enphase_battery_max_percent, result)), 2)

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
