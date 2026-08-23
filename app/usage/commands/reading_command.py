from __future__ import annotations

from datetime import date
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.meter_reader import MeterReader
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


class ReadingCommand:
    """Meter readings: the dashboard, the entries list, CRUD and photo extraction."""

    def __init__(self, database: Database, meter_reader: MeterReader) -> None:
        self._database = database
        self._meter_reader = meter_reader

    def dashboard(self, user: SessionUser) -> dict[str, Any]:
        house_ids = self._visible_house_ids(user)
        houses = [
            house
            for house in self._database.decrypt_rows(
                self._database.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
                ("name",),
            )
            if int(house["id"]) in house_ids
        ]
        meters = [
            meter
            for meter in self._database.decrypt_rows(
                self._database.fetch_all(
                    """
                    SELECT id, house_id, kind, label_sealed AS label, unit
                    FROM meters WHERE active ORDER BY house_id, position, id
                    """,
                ),
                ("label",),
            )
            if int(meter["house_id"]) in house_ids
        ]
        registers = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, meter_id, label_sealed AS label, position
                FROM registers WHERE active ORDER BY meter_id, position
                """,
            ),
            ("label",),
        )
        for meter in meters:
            meter["registers"] = [
                {"id": int(register["id"]), "label": register["label"]}
                for register in registers
                if int(register["meter_id"]) == int(meter["id"])
            ]
        return {"houses": houses, "meters": meters}

    def list_readings(self, user: SessionUser, house_id: int, page: int) -> dict[str, Any]:
        self._require_house(user, house_id)
        total_row = self._database.fetch_one(
            """
            SELECT COUNT(DISTINCT readings.read_on) AS count FROM readings
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            """,
            (house_id,),
        )
        total = int(total_row["count"]) if total_row is not None else 0
        pages = max(1, -(-total // Constants.page_size))
        current = min(max(1, page), pages)
        dates = self._database.fetch_all(
            """
            SELECT DISTINCT readings.read_on FROM readings
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            ORDER BY readings.read_on DESC
            LIMIT %s OFFSET %s
            """,
            (house_id, Constants.page_size, (current - 1) * Constants.page_size),
        )
        readings = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT readings.id, readings.meter_id, readings.read_on, readings.source,
                       meters.kind, meters.label_sealed AS meter_label, meters.unit
                FROM readings
                JOIN meters ON meters.id = readings.meter_id
                WHERE meters.house_id = %s AND readings.read_on = ANY(%s)
                ORDER BY readings.read_on DESC, readings.id DESC
                """,
                (house_id, [row["read_on"] for row in dates]),
            ),
            ("meter_label",),
        )
        values = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT reading_values.reading_id, reading_values.register_id, reading_values.value,
                       registers.label_sealed AS label, registers.position
                FROM reading_values
                JOIN registers ON registers.id = reading_values.register_id
                WHERE reading_values.reading_id = ANY(%s)
                ORDER BY reading_values.reading_id, registers.position
                """,
                ([int(reading["id"]) for reading in readings],),
            ),
            ("label",),
        )
        for reading in readings:
            reading["read_on"] = str(reading["read_on"])
            reading["values"] = [
                {
                    "register_id": int(value["register_id"]),
                    "label": value["label"],
                    "value": float(value["value"]),
                }
                for value in values
                if int(value["reading_id"]) == int(reading["id"])
            ]
        return {"readings": readings, "total": total, "page": current, "pages": pages}

    def create_reading(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        meter_id = int(data.get("meter_id") or 0)
        self._require_meter(user, meter_id)
        read_on = self._valid_date(str(data.get("read_on") or ""))
        source = str(data.get("source") or Constants.source_manual)
        if source not in (Constants.source_manual, Constants.source_photo):
            raise AppException(400, "Unknown reading source.")
        values = self._register_values(meter_id, list(data.get("values") or []))
        existing = self._database.fetch_one(
            "SELECT id FROM readings WHERE meter_id = %s AND read_on = %s",
            (meter_id, read_on),
        )
        if existing is not None:
            raise AppException(409, "A reading already exists for this meter and date.")
        with self._database.transaction():
            reading_id = self._database.execute(
                "INSERT INTO readings(meter_id, read_on, source, created_by) VALUES (%s, %s, %s, %s) RETURNING id",
                (meter_id, read_on, source, user.user_id),
            )
            for register_id, value in values:
                self._database.execute(
                    "INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)",
                    (reading_id, register_id, value),
                )
        return {"id": reading_id}

    def update_reading(self, user: SessionUser, reading_id: int, data: dict[str, Any]) -> dict[str, str]:
        reading = self._require_reading(user, reading_id)
        meter_id = int(reading["meter_id"])
        read_on = self._valid_date(str(data.get("read_on") or ""))
        values = self._register_values(meter_id, list(data.get("values") or []))
        duplicate = self._database.fetch_one(
            "SELECT id FROM readings WHERE meter_id = %s AND read_on = %s AND id != %s",
            (meter_id, read_on, reading_id),
        )
        if duplicate is not None:
            raise AppException(409, "A reading already exists for this meter and date.")
        with self._database.transaction():
            self._database.execute(
                "UPDATE readings SET read_on = %s WHERE id = %s",
                (read_on, reading_id),
            )
            for register_id, value in values:
                self._database.execute(
                    """
                    INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)
                    ON CONFLICT (reading_id, register_id) DO UPDATE SET value = EXCLUDED.value
                    """,
                    (reading_id, register_id, value),
                )
        return {"message": "Reading updated."}

    def delete_reading(self, user: SessionUser, reading_id: int) -> dict[str, str]:
        self._require_reading(user, reading_id)
        self._database.execute("DELETE FROM readings WHERE id = %s", (reading_id,))
        return {"message": "Reading deleted."}

    def extract(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        meter_id = int(data.get("meter_id") or 0)
        self._require_meter(user, meter_id)
        media_type = str(data.get("media_type") or "")
        if media_type not in Constants.photo_media_types:
            raise AppException(400, "Unsupported photo format.")
        image_base64 = str(data.get("image_base64") or "")
        if not image_base64:
            raise AppException(400, "Provide a photo.")
        if len(image_base64) * 3 // 4 > Constants.photo_max_bytes:
            raise AppException(400, "The photo is too large.")
        registers = self._active_registers(meter_id)
        values = self._meter_reader.read(image_base64, media_type, [str(register["label"]) for register in registers])
        return {
            "values": [
                {"register_id": int(register["id"]), "label": register["label"], "value": value}
                for register, value in zip(registers, values)
            ],
        }

    def reminder_states(self, user: SessionUser) -> dict[str, Any]:
        # Reminders are on by default: only explicit opt-outs are stored as rows.
        rows = self._database.fetch_all(
            "SELECT house_id FROM reminders WHERE user_id = %s AND NOT enabled ORDER BY house_id",
            (user.user_id,),
        )
        return {"disabled_house_ids": [int(row["house_id"]) for row in rows]}

    def set_reminder(self, user: SessionUser, data: dict[str, Any]) -> dict[str, str]:
        house_id = int(data.get("house_id") or 0)
        enabled = bool(data.get("enabled"))
        self._require_house(user, house_id)
        self._database.execute(
            """
            INSERT INTO reminders(user_id, house_id, enabled) VALUES (%s, %s, %s)
            ON CONFLICT (user_id, house_id) DO UPDATE SET enabled = EXCLUDED.enabled
            """,
            (user.user_id, house_id, enabled),
        )
        result = "Monthly reminder enabled for this house." if enabled else "Monthly reminder disabled for this house."
        return {"message": result}

    def _visible_house_ids(self, user: SessionUser) -> list[int]:
        if user.is_admin:
            rows = self._database.fetch_all("SELECT id FROM houses ORDER BY id")
            return [int(row["id"]) for row in rows]
        rows = self._database.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (user.user_id,))
        return [int(row["house_id"]) for row in rows]

    def _require_house(self, user: SessionUser, house_id: int) -> None:
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        if house_id not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")

    def _require_meter(self, user: SessionUser, meter_id: int) -> dict[str, Any]:
        result = self._database.fetch_one("SELECT id, house_id FROM meters WHERE id = %s", (meter_id,))
        if result is None:
            raise AppException(404, "The meter was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result

    def _require_reading(self, user: SessionUser, reading_id: int) -> dict[str, Any]:
        result = self._database.fetch_one(
            """
            SELECT readings.id, readings.meter_id, meters.house_id
            FROM readings JOIN meters ON meters.id = readings.meter_id
            WHERE readings.id = %s
            """,
            (reading_id,),
        )
        if result is None:
            raise AppException(404, "The reading was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result

    def _active_registers(self, meter_id: int) -> list[dict[str, Any]]:
        return self._database.decrypt_rows(
            self._database.fetch_all(
                "SELECT id, label_sealed AS label FROM registers WHERE meter_id = %s AND active ORDER BY position",
                (meter_id,),
            ),
            ("label",),
        )

    def _register_values(self, meter_id: int, values: list[dict[str, Any]]) -> list[tuple[int, float]]:
        registers = self._active_registers(meter_id)
        expected_ids = {int(register["id"]) for register in registers}
        provided = {int(value.get("register_id") or 0): float(value.get("value") or 0) for value in values}
        if set(provided.keys()) != expected_ids:
            raise AppException(400, "Provide a value for each register of the meter.")
        return [(int(register["id"]), provided[int(register["id"])]) for register in registers]

    def _valid_date(self, value: str) -> str:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise AppException(400, "Enter a valid date.") from None
