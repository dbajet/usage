from __future__ import annotations

from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


class MeterCommand:
    """Meters and their registers, managed by every user linked to the house."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def list_meters(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_house(user, house_id)
        registers = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT registers.id, registers.meter_id, registers.label_sealed AS label,
                       registers.initial_value, registers.position, registers.active
                FROM registers JOIN meters ON meters.id = registers.meter_id
                WHERE meters.house_id = %s ORDER BY registers.meter_id, registers.position
                """,
                (house_id,),
            ),
            ("label",),
        )
        meters = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, house_id, kind, label_sealed AS label, unit, position, active
                FROM meters WHERE house_id = %s ORDER BY position, id
                """,
                (house_id,),
            ),
            ("label",),
        )
        for meter in meters:
            meter["registers"] = [
                {
                    "id": int(register["id"]),
                    "label": register["label"],
                    "initial_value": float(register["initial_value"]),
                    "position": int(register["position"]),
                    "active": bool(register["active"]),
                }
                for register in registers
                if int(register["meter_id"]) == int(meter["id"])
            ]
        return {"meters": meters}

    def create_meter(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        house_id = int(data.get("house_id") or 0)
        kind = str(data.get("kind") or "")
        if kind not in Constants.kinds:
            raise AppException(400, "Unknown meter kind.")
        self._require_house(user, house_id)
        registers = list(data.get("registers") or [{}])
        if not 1 <= len(registers) <= 2:
            raise AppException(400, "A meter has one or two registers.")
        with self._database.transaction():
            meter_id = self._database.execute(
                """
                INSERT INTO meters(house_id, kind, label_sealed, unit)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    house_id,
                    kind,
                    self._database.encrypt(str(data.get("label") or "").strip()),
                    str(data.get("unit") or "").strip(),
                ),
            )
            for position, register in enumerate(registers):
                self._database.execute(
                    """
                    INSERT INTO registers(meter_id, label_sealed, initial_value, position)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        meter_id,
                        self._database.encrypt(str(register.get("label") or "").strip()),
                        float(register.get("initial_value") or 0),
                        position,
                    ),
                )
        return {"id": meter_id}

    def update_meter(self, user: SessionUser, meter_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_meter(user, meter_id)
        self._database.execute(
            "UPDATE meters SET label_sealed = %s, unit = %s, active = %s WHERE id = %s",
            (
                self._database.encrypt(str(data.get("label") or "").strip()),
                str(data.get("unit") or "").strip(),
                bool(data.get("active")),
                meter_id,
            ),
        )
        return {"message": "Meter updated."}

    def delete_meter(self, user: SessionUser, meter_id: int) -> dict[str, str]:
        self._require_meter(user, meter_id)
        self._database.execute("DELETE FROM meters WHERE id = %s", (meter_id,))
        return {"message": "Meter deleted, along with its readings."}

    def create_register(self, user: SessionUser, meter_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._require_meter(user, meter_id)
        active = self._database.fetch_one(
            "SELECT COUNT(*) AS count, COALESCE(MAX(position), -1) AS top FROM registers WHERE meter_id = %s AND active",
            (meter_id,),
        )
        if active is not None and int(active["count"]) >= 2:
            raise AppException(400, "A meter has at most two active registers.")
        register_id = self._database.execute(
            """
            INSERT INTO registers(meter_id, label_sealed, initial_value, position)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                meter_id,
                self._database.encrypt(str(data.get("label") or "").strip()),
                float(data.get("initial_value") or 0),
                int(active["top"]) + 1 if active is not None else 0,
            ),
        )
        return {"id": register_id}

    def update_register(self, user: SessionUser, register_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_register(user, register_id)
        self._database.execute(
            "UPDATE registers SET label_sealed = %s, initial_value = %s, active = %s WHERE id = %s",
            (
                self._database.encrypt(str(data.get("label") or "").strip()),
                float(data.get("initial_value") or 0),
                bool(data.get("active")),
                register_id,
            ),
        )
        return {"message": "Register updated."}

    def delete_register(self, user: SessionUser, register_id: int) -> dict[str, str]:
        self._require_register(user, register_id)
        values = self._database.fetch_one(
            "SELECT COUNT(*) AS count FROM reading_values WHERE register_id = %s",
            (register_id,),
        )
        if values is not None and int(values["count"]) > 0:
            raise AppException(409, "This register has readings. Deactivate it instead.")
        self._database.execute("DELETE FROM registers WHERE id = %s", (register_id,))
        return {"message": "Register deleted."}

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

    def _require_register(self, user: SessionUser, register_id: int) -> dict[str, Any]:
        result = self._database.fetch_one(
            """
            SELECT registers.id, meters.house_id
            FROM registers JOIN meters ON meters.id = registers.meter_id
            WHERE registers.id = %s
            """,
            (register_id,),
        )
        if result is None:
            raise AppException(404, "The register was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result
