from __future__ import annotations

from typing import Any

from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser


class StatsCommand:
    """Derived consumption: per-kind month/year tables and per-meter trend series.

    Consumption is never stored - it is the difference between consecutive
    counter readings, attributed to the month of the later reading. When
    months were skipped, the difference is spread evenly over the unmeasured
    months. The register's initial value is the baseline of its first reading.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def tables(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_house(user, house_id)
        meters, consumption = self._house_consumption(user, house_id)
        kinds: list[dict[str, Any]] = []
        # The kinds follow the user's own meter order, not a fixed one.
        ordered_kinds: list[str] = []
        for meter in meters:
            if str(meter["kind"]) not in ordered_kinds:
                ordered_kinds.append(str(meter["kind"]))
        for kind in ordered_kinds:
            kind_meters = [meter for meter in meters if str(meter["kind"]) == kind]
            merged: dict[int, float] = {}
            for meter in kind_meters:
                for month, value in consumption.get(int(meter["id"]), {}).items():
                    merged[month] = merged.get(month, 0.0) + value
            if not merged:
                continue
            unit = next((str(meter["unit"]) for meter in kind_meters if meter["unit"]), "")
            kinds.append({"kind": kind, "unit": unit, "years": self._years(merged)})
        return {"kinds": kinds}

    def series(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_house(user, house_id)
        meters, consumption = self._house_consumption(user, house_id)
        result: list[dict[str, Any]] = []
        for meter in meters:
            months = consumption.get(int(meter["id"]), {})
            if not months:
                continue
            result.append(
                {
                    "meter_id": int(meter["id"]),
                    "label": meter["label"] or str(meter["kind"]),
                    "kind": str(meter["kind"]),
                    "unit": str(meter["unit"]),
                    "points": [
                        {"month": self._month_key(month), "value": round(months[month], 2)}
                        for month in sorted(months)
                    ],
                },
            )
        return {"series": result}

    def _house_consumption(self, user: SessionUser, house_id: int) -> tuple[list[dict[str, Any]], dict[int, dict[int, float]]]:
        meters = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT meters.id, meters.kind, meters.label_sealed AS label, meters.unit
                FROM meters
                LEFT JOIN meter_orders ON meter_orders.meter_id = meters.id AND meter_orders.user_id = %s
                WHERE meters.house_id = %s
                ORDER BY COALESCE(meter_orders.position, meters.position), meters.position, meters.id
                """,
                (user.user_id, house_id),
            ),
            ("label",),
        )
        registers = self._database.fetch_all(
            """
            SELECT registers.id, registers.meter_id, registers.initial_value
            FROM registers JOIN meters ON meters.id = registers.meter_id
            WHERE meters.house_id = %s ORDER BY registers.id
            """,
            (house_id,),
        )
        rows = self._database.fetch_all(
            """
            SELECT readings.meter_id, readings.read_on, reading_values.register_id, reading_values.value
            FROM readings JOIN reading_values ON reading_values.reading_id = readings.id
            JOIN meters ON meters.id = readings.meter_id
            WHERE meters.house_id = %s
            ORDER BY readings.read_on, readings.id
            """,
            (house_id,),
        )
        result: dict[int, dict[int, float]] = {}
        for register in registers:
            register_id = int(register["id"])
            meter_id = int(register["meter_id"])
            points = [
                (self._month_index(str(row["read_on"])), float(row["value"]))
                for row in rows
                if int(row["register_id"]) == register_id
            ]
            monthly = self._register_consumption(float(register["initial_value"]), points)
            target = result.setdefault(meter_id, {})
            for month, value in monthly.items():
                target[month] = target.get(month, 0.0) + value
        return meters, result

    @classmethod
    def _register_consumption(cls, initial_value: float, points: list[tuple[int, float]]) -> dict[int, float]:
        result: dict[int, float] = {}
        if not points:
            return result
        first_index, first_value = points[0]
        result[first_index] = first_value - initial_value
        previous_index, previous_value = points[0]
        for index, value in points[1:]:
            delta = value - previous_value
            gap = index - previous_index
            if gap <= 0:
                result[index] = result.get(index, 0.0) + delta
            else:
                # Unmeasured months get an even share of the delta.
                share = delta / gap
                for month in range(previous_index + 1, index + 1):
                    result[month] = result.get(month, 0.0) + share
            previous_index, previous_value = index, value
        return result

    @classmethod
    def _years(cls, merged: dict[int, float]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        first_year = min(merged) // 12
        last_year = max(merged) // 12
        for year in range(first_year, last_year + 1):
            months: list[float | None] = []
            for month in range(12):
                value = merged.get(year * 12 + month)
                months.append(round(value, 2) if value is not None else None)
            total = round(sum(value for value in months if value is not None), 2)
            result.append({"year": year, "months": months, "total": total})
        return result

    @classmethod
    def _month_index(cls, read_on: str) -> int:
        return int(read_on[:4]) * 12 + int(read_on[5:7]) - 1

    @classmethod
    def _month_key(cls, index: int) -> str:
        return f"{index // 12:04d}-{index % 12 + 1:02d}"

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
