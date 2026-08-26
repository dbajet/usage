from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.import_row import ImportRow


class ImportCommand:
    """One-shot import of the historical spreadsheet exports (tab-separated).

    The files carry an "Arrivee" row with the counters at arrival - the
    register baselines - then one row per month with the cumulative counters
    for EDF, GDF and Water. Two spreadsheet events are reproduced faithfully:
    a counter dropping below its predecessor means the meter was replaced (a
    new register starts at zero), and the appearance of HC/HP columns means
    the electricity meter became dual-register (the single register stops on
    the first split month, whose HC/HP values become the new baselines).
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def run(self, csv_path: Path, house_name: str) -> dict[str, Any]:
        if self._house_exists(house_name):
            raise AppException(409, f"The house '{house_name}' already exists - the history was probably imported.")
        initials, rows = self._parse(csv_path)
        result: dict[str, Any] = {"house": house_name, "meters": 3, "registers": 0, "readings": 0, "values": 0}
        with self._database.transaction():
            house_id = self._database.execute(
                "INSERT INTO houses(name_sealed) VALUES (%s) RETURNING id",
                (self._database.encrypt(house_name),),
            )
            edf_id = self._insert_meter(house_id, Constants.kind_electricity, "EDF", "kWh", 0)
            gdf_id = self._insert_meter(house_id, Constants.kind_gas, "GDF", "m3", 1)
            water_id = self._insert_meter(house_id, Constants.kind_water, "Water", "m3", 2)
            counts = [
                self._import_split(edf_id, initials["edf"], rows),
                self._import_simple(gdf_id, initials["gdf"], [(row.read_on, row.gdf) for row in rows]),
                self._import_simple(water_id, initials["water"], [(row.read_on, row.water) for row in rows]),
            ]
            for registers, readings, values in counts:
                result["registers"] += registers
                result["readings"] += readings
                result["values"] += values
        return result

    def import_mileage(self, csv_path: Path, house_name: str, label: str) -> dict[str, Any]:
        """Mileage history (month + odometer per line) added to an existing house.

        The first line with a value is the baseline: the register starts there,
        so the first month shows no consumption. Empty months are skipped and
        their consumption is spread by the stats, like any gap.
        """
        house_id = self._house_id(house_name)
        if house_id == 0:
            raise AppException(404, f"The house '{house_name}' was not found - import its history first.")
        if self._meter_exists(house_id, label):
            raise AppException(409, f"The meter '{label}' already exists - the mileage was probably imported.")
        points = self._parse_mileage(csv_path)
        if not points:
            raise AppException(400, "The file holds no readings.")
        result: dict[str, Any] = {"house": house_name, "meters": 1, "registers": 0, "readings": 0, "values": 0}
        with self._database.transaction():
            position_row = self._database.fetch_one(
                "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM meters WHERE house_id = %s",
                (house_id,),
            )
            position = int(position_row["position"]) if position_row is not None else 0
            meter_id = self._insert_meter(house_id, Constants.kind_mileage, label, "km", position)
            registers, readings, values = self._import_simple(meter_id, points[0][1], points)
            result["registers"] += registers
            result["readings"] += readings
            result["values"] += values
        return result

    def _parse_mileage(self, csv_path: Path) -> list[tuple[str, float]]:
        result: list[tuple[str, float]] = []
        for line in csv_path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            read_on = self._month_date(fields[0].strip())
            value = self._number(fields[1])
            if not read_on or value is None:
                continue
            result.append((read_on, value))
        return result

    def _house_id(self, house_name: str) -> int:
        rows = self._database.decrypt_rows(
            self._database.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
            ("name",),
        )
        normalized = house_name.strip().lower()
        for row in rows:
            if str(row["name"]).strip().lower() == normalized:
                return int(row["id"])
        return 0

    def _meter_exists(self, house_id: int, label: str) -> bool:
        rows = self._database.decrypt_rows(
            self._database.fetch_all("SELECT id, label_sealed AS label FROM meters WHERE house_id = %s ORDER BY id", (house_id,)),
            ("label",),
        )
        normalized = label.strip().lower()
        return any(str(row["label"]).strip().lower() == normalized for row in rows)

    def _house_exists(self, house_name: str) -> bool:
        rows = self._database.decrypt_rows(
            self._database.fetch_all("SELECT id, name_sealed AS name FROM houses ORDER BY id"),
            ("name",),
        )
        normalized = house_name.strip().lower()
        return any(str(row["name"]).strip().lower() == normalized for row in rows)

    def _parse(self, csv_path: Path) -> tuple[dict[str, float], list[ImportRow]]:
        initials = {"edf": 0.0, "gdf": 0.0, "water": 0.0}
        rows: list[ImportRow] = []
        for line in csv_path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) < 10:
                continue
            counters = [self._number(fields[7]), self._number(fields[8]), self._number(fields[9])]
            if counters[0] is None or counters[1] is None or counters[2] is None:
                continue
            if fields[0].strip() == "Arrivee":
                initials = {"edf": counters[0], "gdf": counters[1], "water": counters[2]}
                continue
            read_on = self._month_date(fields[0].strip())
            if not read_on:
                continue
            hc = self._number(fields[5])
            hp = self._number(fields[6])
            if hc is None or hp is None or abs(hc + hp - counters[0]) > 1.0:
                # Only a genuine register split sums to the meter counter -
                # Dougmar's enphase measurements share these columns and don't.
                hc = None
                hp = None
            rows.append(
                ImportRow(
                    read_on=read_on,
                    edf=counters[0],
                    gdf=counters[1],
                    water=counters[2],
                    hc=hc,
                    hp=hp,
                ),
            )
        return initials, rows

    def _import_simple(self, meter_id: int, initial: float, points: list[tuple[str, float]]) -> tuple[int, int, int]:
        """Insert one register and its readings; a counter drop starts a replacement register."""
        register_id = self._insert_register(meter_id, "", initial, 0, True)
        registers = 1
        readings = 0
        previous = initial
        for read_on, value in points:
            if value < previous:
                # The counter went backwards: the meter was replaced.
                self._database.execute("UPDATE registers SET active = false WHERE id = %s", (register_id,))
                register_id = self._insert_register(meter_id, "", 0.0, registers, True)
                registers += 1
            reading_id = self._insert_reading(meter_id, read_on)
            self._insert_value(reading_id, register_id, value)
            readings += 1
            previous = value
        return registers, readings, readings

    def _import_split(self, meter_id: int, initial: float, rows: list[ImportRow]) -> tuple[int, int, int]:
        """Electricity: the summed counter until the first HC/HP month, split registers after it."""
        split_rows = [row for row in rows if row.hc is not None and row.hp is not None]
        first_split = split_rows[0].read_on if split_rows else ""
        main_points = [(row.read_on, row.edf) for row in rows if not first_split or row.read_on <= first_split]
        registers, readings, values = self._import_simple(meter_id, initial, main_points)
        if not split_rows:
            return registers, readings, values
        self._database.execute("UPDATE registers SET active = false WHERE meter_id = %s", (meter_id,))
        hc_id = self._insert_register(meter_id, "HC", float(split_rows[0].hc or 0), registers, True)
        hp_id = self._insert_register(meter_id, "HP", float(split_rows[0].hp or 0), registers + 1, True)
        registers += 2
        for row in split_rows[1:]:
            reading_id = self._insert_reading(meter_id, row.read_on)
            self._insert_value(reading_id, hc_id, float(row.hc or 0))
            self._insert_value(reading_id, hp_id, float(row.hp or 0))
            readings += 1
            values += 2
        return registers, readings, values

    def _insert_meter(self, house_id: int, kind: str, label: str, unit: str, position: int) -> int:
        return self._database.execute(
            "INSERT INTO meters(house_id, kind, label_sealed, unit, position) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (house_id, kind, self._database.encrypt(label), unit, position),
        )

    def _insert_register(self, meter_id: int, label: str, initial: float, position: int, active: bool) -> int:
        return self._database.execute(
            """
            INSERT INTO registers(meter_id, label_sealed, initial_value, position, active)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (meter_id, self._database.encrypt(label), initial, position, active),
        )

    def _insert_reading(self, meter_id: int, read_on: str) -> int:
        return self._database.execute(
            "INSERT INTO readings(meter_id, read_on, source) VALUES (%s, %s, %s) RETURNING id",
            (meter_id, read_on, Constants.source_import),
        )

    def _insert_value(self, reading_id: int, register_id: int, value: float) -> None:
        self._database.execute(
            "INSERT INTO reading_values(reading_id, register_id, value) VALUES (%s, %s, %s)",
            (reading_id, register_id, value),
        )

    def _month_date(self, value: str) -> str:
        try:
            # Readings are monthly; the annotations in the files point at mid-month.
            return datetime.strptime(value, "%b-%Y").replace(day=15).date().isoformat()
        except ValueError:
            return ""

    def _number(self, value: str) -> float | None:
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return None
