from __future__ import annotations

from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


class AdminCommand:
    """Admin-only management of users, houses, user-house links, meters and registers."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def overview(self, user: SessionUser) -> dict[str, Any]:
        self._require_admin(user)
        links = self._database.fetch_all("SELECT user_id, house_id FROM user_houses ORDER BY id")
        users = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, email_sealed AS email, name_sealed AS name, is_admin, last_login_at
                FROM users ORDER BY id
                """,
            ),
            ("email", "name"),
        )
        for row in users:
            row["house_ids"] = [int(link["house_id"]) for link in links if int(link["user_id"]) == int(row["id"])]
            row["last_login_at"] = str(row["last_login_at"] or "")
        return {
            "users": users,
            "houses": self._houses(),
            "meters": self._meters(),
        }

    def create_user(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        self._require_admin(user)
        email = str(data.get("email") or "").strip().lower()
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise AppException(400, "Enter a valid email address.")
        email_hash = self._database.blind_index(email)
        existing = self._database.fetch_one("SELECT id FROM users WHERE email_hash = %s", (email_hash,))
        if existing is not None:
            raise AppException(409, "A user with this email already exists.")
        user_id = self._database.execute(
            """
            INSERT INTO users(email_sealed, email_hash, name_sealed, is_admin)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (
                self._database.encrypt(email),
                email_hash,
                self._database.encrypt(str(data.get("name") or "").strip()),
                bool(data.get("is_admin")),
            ),
        )
        return {"id": user_id}

    def update_user(self, user: SessionUser, user_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        if user_id == user.user_id and not bool(data.get("is_admin")):
            raise AppException(400, "You cannot remove your own admin access.")
        row = self._database.fetch_one("SELECT id FROM users WHERE id = %s", (user_id,))
        if row is None:
            raise AppException(404, "The user was not found.")
        self._database.execute(
            "UPDATE users SET name_sealed = %s, is_admin = %s WHERE id = %s",
            (self._database.encrypt(str(data.get("name") or "").strip()), bool(data.get("is_admin")), user_id),
        )
        return {"message": "User updated."}

    def delete_user(self, user: SessionUser, user_id: int) -> dict[str, str]:
        self._require_admin(user)
        if user_id == user.user_id:
            raise AppException(400, "You cannot delete your own account.")
        row = self._database.fetch_one("SELECT id FROM users WHERE id = %s", (user_id,))
        if row is None:
            raise AppException(404, "The user was not found.")
        self._database.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return {"message": "User deleted."}

    def create_house(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        self._require_admin(user)
        name = str(data.get("name") or "").strip()
        if not name:
            raise AppException(400, "Enter a house name.")
        house_id = self._database.execute(
            "INSERT INTO houses(name_sealed) VALUES (%s) RETURNING id",
            (self._database.encrypt(name),),
        )
        return {"id": house_id}

    def update_house(self, user: SessionUser, house_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        name = str(data.get("name") or "").strip()
        if not name:
            raise AppException(400, "Enter a house name.")
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        self._database.execute(
            "UPDATE houses SET name_sealed = %s WHERE id = %s",
            (self._database.encrypt(name), house_id),
        )
        return {"message": "House updated."}

    def delete_house(self, user: SessionUser, house_id: int) -> dict[str, str]:
        self._require_admin(user)
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        self._database.execute("DELETE FROM houses WHERE id = %s", (house_id,))
        return {"message": "House deleted."}

    def set_user_house(self, user: SessionUser, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        user_id = int(data.get("user_id") or 0)
        house_id = int(data.get("house_id") or 0)
        target = self._database.fetch_one("SELECT id FROM users WHERE id = %s", (user_id,))
        house = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if target is None or house is None:
            raise AppException(404, "The user or house was not found.")
        if bool(data.get("linked")):
            self._database.execute(
                "INSERT INTO user_houses(user_id, house_id) VALUES (%s, %s) ON CONFLICT (user_id, house_id) DO NOTHING",
                (user_id, house_id),
            )
            return {"message": "User linked to the house."}
        self._database.execute(
            "DELETE FROM user_houses WHERE user_id = %s AND house_id = %s",
            (user_id, house_id),
        )
        return {"message": "User unlinked from the house."}

    def create_meter(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        self._require_admin(user)
        house_id = int(data.get("house_id") or 0)
        kind = str(data.get("kind") or "")
        if kind not in Constants.kinds:
            raise AppException(400, "Unknown meter kind.")
        house = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if house is None:
            raise AppException(404, "The house was not found.")
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
        self._require_admin(user)
        row = self._database.fetch_one("SELECT id FROM meters WHERE id = %s", (meter_id,))
        if row is None:
            raise AppException(404, "The meter was not found.")
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
        self._require_admin(user)
        row = self._database.fetch_one("SELECT id FROM meters WHERE id = %s", (meter_id,))
        if row is None:
            raise AppException(404, "The meter was not found.")
        self._database.execute("DELETE FROM meters WHERE id = %s", (meter_id,))
        return {"message": "Meter deleted, along with its readings."}

    def create_register(self, user: SessionUser, meter_id: int, data: dict[str, Any]) -> dict[str, Any]:
        self._require_admin(user)
        meter = self._database.fetch_one("SELECT id FROM meters WHERE id = %s", (meter_id,))
        if meter is None:
            raise AppException(404, "The meter was not found.")
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
        self._require_admin(user)
        row = self._database.fetch_one("SELECT id FROM registers WHERE id = %s", (register_id,))
        if row is None:
            raise AppException(404, "The register was not found.")
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
        self._require_admin(user)
        row = self._database.fetch_one("SELECT id FROM registers WHERE id = %s", (register_id,))
        if row is None:
            raise AppException(404, "The register was not found.")
        values = self._database.fetch_one(
            "SELECT COUNT(*) AS count FROM reading_values WHERE register_id = %s",
            (register_id,),
        )
        if values is not None and int(values["count"]) > 0:
            raise AppException(409, "This register has readings. Deactivate it instead.")
        self._database.execute("DELETE FROM registers WHERE id = %s", (register_id,))
        return {"message": "Register deleted."}

    def _houses(self) -> list[dict[str, Any]]:
        return self._database.decrypt_rows(
            self._database.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
            ("name",),
        )

    def _meters(self) -> list[dict[str, Any]]:
        registers = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, meter_id, label_sealed AS label, initial_value, position, active
                FROM registers ORDER BY meter_id, position
                """,
            ),
            ("label",),
        )
        result = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, house_id, kind, label_sealed AS label, unit, position, active
                FROM meters ORDER BY house_id, position, id
                """,
            ),
            ("label",),
        )
        for meter in result:
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
        return result

    def _require_admin(self, user: SessionUser) -> None:
        if not user.is_admin:
            raise AppException(403, "Only admins can do this.")
