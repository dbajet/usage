from __future__ import annotations

import hashlib
import math
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.session_user import SessionUser


class SensorCommand:
    """Sensors fed by Home Assistant: timestamped samples (temperatures) per house.

    Home Assistant posts a batch of current states every few minutes, signed
    with the house's sensor token. An unknown entity becomes a sensor on the
    fly, named by the Home Assistant configuration; users rename, order and
    hide sensors in Settings (a hidden sensor keeps collecting, out of the
    graphs - a deleted one would only come back on the next push). A sample
    is keyed by the sensor and the
    instant its value last changed, so a value re-sent unchanged is a no-op
    rather than a duplicate.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def ingest(self, authorization: str, data: dict[str, Any]) -> dict[str, int]:
        house_id = self._house_from_token(authorization)
        samples = list(data.get("samples") or [])
        if len(samples) > Constants.ingest_max_samples:
            raise AppException(400, f"At most {Constants.ingest_max_samples} samples per request.")
        parsed = [self._parse_sample(sample) for sample in samples]
        known: dict[str, int] = {}
        created = 0
        with self._database.transaction():
            for sample in parsed:
                if sample.entity_id not in known:
                    sensor_id, is_new = self._find_or_create_sensor(house_id, sample)
                    known[sample.entity_id] = sensor_id
                    created += int(is_new)
                self._database.execute(
                    """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (known[sample.entity_id], sample.measured_at.isoformat(), sample.value),
                )
        return {"accepted": len(parsed), "created": created}

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
            (self._hash(token), house_id),
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
                SELECT id, entity_id_sealed AS entity_id, name_sealed AS name, unit, position, active
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
                    "position": int(sensor["position"]),
                    "active": bool(sensor["active"]),
                    "last_value": float(last["value"]) if last is not None else None,
                    "last_at": last["measured_at"].isoformat() if last is not None else "",
                },
            )
        return {"sensors": result}

    def update_sensor(self, user: SessionUser, sensor_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_sensor(user, sensor_id)
        name = str(data.get("name") or "").strip()
        if not name:
            raise AppException(400, "Enter a sensor name.")
        self._database.execute(
            "UPDATE sensors SET name_sealed = %s, unit = %s, active = %s WHERE id = %s",
            (
                self._database.encrypt(name),
                str(data.get("unit") or "").strip(),
                bool(data.get("active")),
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

    def series(self, user: SessionUser, house_id: int, days: int, previous: bool) -> dict[str, Any]:
        """Per active sensor, the samples of the last `days` averaged per time bucket.

        With `previous`, the window doubles so the caller can overlay the
        period before (the buckets are day-aligned, so shifting by `days`
        lines them up).
        """
        self._require_house(user, house_id)
        bucket_minutes = dict(Constants.sensor_ranges).get(days)
        if bucket_minutes is None:
            choices = ", ".join(str(range_days) for range_days, _ in Constants.sensor_ranges)
            raise AppException(400, f"The range must be one of {choices} days.")
        since = datetime.now(UTC) - timedelta(days=days * (2 if previous else 1))
        sensors = self._database.decrypt_rows(
            self._database.fetch_all(
                "SELECT id, name_sealed AS name, unit FROM sensors WHERE house_id = %s AND active ORDER BY position, id",
                (house_id,),
            ),
            ("name",),
        )
        rows = self._database.fetch_all(
            """
            SELECT samples.sensor_id,
                   date_bin(%s, samples.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   AVG(samples.value) AS average, MIN(samples.value) AS low, MAX(samples.value) AS high
            FROM samples JOIN sensors ON sensors.id = samples.sensor_id
            WHERE sensors.house_id = %s AND sensors.active AND samples.measured_at >= %s
            GROUP BY samples.sensor_id, bucket
            ORDER BY samples.sensor_id, bucket
            """,
            (timedelta(minutes=bucket_minutes), house_id, since.isoformat()),
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
        return {"days": days, "bucket_minutes": bucket_minutes, "previous": previous, "series": result}

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
            INSERT INTO sensors(house_id, entity_id_sealed, entity_hash, name_sealed, unit, position)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                self._database.encrypt(sample.entity_id),
                entity_hash,
                self._database.encrypt(sample.name),
                sample.unit,
                int(count["count"]) if count is not None else 0,
            ),
        )
        return sensor_id, True

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
        )

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

    def _house_from_token(self, authorization: str) -> int:
        scheme, _, token = authorization.strip().partition(" ")
        if scheme.lower() != "bearer":
            token = authorization
        token = token.strip()
        if not token:
            raise AppException(401, "A sensor token is required.")
        row = self._database.fetch_one(
            "SELECT id FROM houses WHERE ingest_token_hash = %s AND ingest_token_hash <> ''",
            (self._hash(token),),
        )
        if row is None:
            raise AppException(401, "The sensor token is not valid.")
        return int(row["id"])

    @classmethod
    def _hash(cls, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

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
