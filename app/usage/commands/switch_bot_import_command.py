from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample


class SwitchBotImportCommand:
    """The history a meter keeps on itself, once somebody has exported it.

    SwitchBot's cloud serves no history at all, but every meter keeps its own -
    36 days on a Meter, 68 on a Meter Plus or an Outdoor one - and the phone
    reads it over Bluetooth and writes it out as a CSV. That file is the only
    way back past the day a feed was added, and it is a one-off: the readings
    land in `samples` beside everything else, and once a fortnight is stored it
    never has to be asked for again.

    The file says one thing over and over. It carries a row a minute whether or
    not anything moved - seventeen days of one wine cellar is twenty-four
    thousand rows and sixty-nine changes - and this app has held from the start
    that a value re-sent unchanged is the same sample, not a new one. So a run
    of identical readings is stored as the instant it began, exactly as a push
    or a pull would store it, and the graph draws the same line from a
    three-hundredth of the rows.

    Its header names the unit, so it is read in the unit it names rather than
    the one it is expected to be in - the rule the water export taught.

    **Its instants carry no offset at all, and they are not the house's time.**
    The app writes them on the clock of the phone that exported them, which is
    a different thing entirely: one real export of a thermometer standing in
    France put its coldest moment at 21:21 and its warmest at 08:26, an
    impossible day anywhere. The shape was right - a nine-hour warming half is
    exactly mid-September at that latitude - so only the labelling was wrong.

    So the zone is told to this rather than assumed. Getting it wrong is silent
    and expensive: it files a fortnight of readings hours from where they
    belong, and they look entirely reasonable sitting there. The house's own
    zone is the fallback and is right only when the phone was in the house.
    The way to be sure is an export that overlaps readings the app collected
    itself, where one matching value settles it to the minute.

    On the autumn fall-back the repeated hour is told apart by the rows being
    in order, the same way the water export's are.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def run(self, csv_path: Path, house_name: str, sensor_name: str = "", timezone: str = "") -> dict[str, Any]:
        """Import one device's export into the sensor it belongs to.

        `timezone` is the clock the export was written on - the exporting
        phone's, not the house's, which is only the same when the two were in
        the same place. It falls back to the house's zone, and the answer it
        used is reported back so a wrong one is visible rather than silent.
        """
        house = self._house(house_name)
        wanted = sensor_name.strip() or self._device_of(csv_path)
        temperature_id, humidity_id = self._sensors(int(house["id"]), wanted)
        zone = timezone.strip() or str(house["timezone"])
        readings = self._parse(csv_path, self._zone(zone))
        if not readings:
            raise AppException(400, f"{csv_path.name} carries no readings.")
        temperatures = self._collapse([sample for sample in readings if sample.unit == Constants.switchbot_temperature_unit])
        humidities = self._collapse([sample for sample in readings if sample.unit == Constants.switchbot_humidity_unit])
        return {
            "house": house_name,
            "sensor": wanted,
            "zone": zone,
            "rows": len(readings),
            "temperature": self._store(temperature_id, temperatures),
            "humidity": self._store(humidity_id, humidities) if humidity_id else 0,
            "from": readings[0].measured_at.isoformat(),
            "to": readings[-1].measured_at.isoformat(),
        }

    def _house(self, house_name: str) -> dict[str, Any]:
        rows = self._database.decrypt_rows(
            self._database.fetch_all("SELECT id, name_sealed AS name, timezone FROM houses ORDER BY id"),
            ("name",),
        )
        normalized = house_name.strip().lower()
        for row in rows:
            if str(row["name"]).strip().lower() == normalized:
                return row
        raise AppException(404, f"No house is called {house_name}.")

    def _sensors(self, house_id: int, device_name: str) -> tuple[int, int]:
        """The thermometer this file belongs to, and the humidity beside it.

        Matched on the name the device carries, which is what the export is
        called after. A sensor renamed in Settings since it arrived is named
        explicitly instead - that is what the second argument is for.
        """
        rows = self._database.decrypt_rows(
            self._database.fetch_all(
                "SELECT id, name_sealed AS name, entity_id_sealed AS entity_id FROM sensors WHERE house_id = %s ORDER BY id",
                (house_id,),
            ),
            ("name", "entity_id"),
        )
        normalized = device_name.strip().lower()
        found = next((row for row in rows if str(row["name"]).strip().lower() == normalized), None)
        if found is None:
            raise AppException(404, f"This house has no thermometer called {device_name}.")
        entity_id = str(found["entity_id"])
        if not entity_id.startswith(Constants.switchbot_entity_prefix):
            raise AppException(400, f"{device_name} is not a SwitchBot thermometer.")
        humidity = f"{entity_id}{Constants.switchbot_humidity_suffix}"
        beside = next((row for row in rows if str(row["entity_id"]) == humidity), None)
        return int(found["id"]), 0 if beside is None else int(beside["id"])

    def _parse(self, csv_path: Path, zone: ZoneInfo) -> list[SensorSample]:
        """Every row of the file, as the samples the two sensors would have stored."""
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            temperature = self._column(columns, Constants.switchbot_export_temperature_prefix)
            humidity = self._column(columns, Constants.switchbot_export_humidity_prefix)
            if not temperature:
                raise AppException(400, f"{csv_path.name} has no temperature column; its header reads {', '.join(columns)}.")
            fahrenheit = Constants.switchbot_export_fahrenheit in temperature.lower()
            result: list[SensorSample] = []
            previous: datetime | None = None
            for line in reader:
                measured_at = self._instant(str(line.get(Constants.switchbot_export_date_column) or ""), zone, previous)
                previous = measured_at
                degrees = self._number(line.get(temperature))
                if degrees is not None:
                    result.append(self._sample(Constants.switchbot_temperature_unit, self._celsius(degrees, fahrenheit), measured_at))
                percent = self._number(line.get(humidity)) if humidity else None
                if percent is not None:
                    result.append(self._sample(Constants.switchbot_humidity_unit, percent, measured_at))
        return result

    @classmethod
    def _sample(cls, unit: str, value: float, measured_at: datetime) -> SensorSample:
        return SensorSample(entity_id="", name="", unit=unit, value=round(value, 2), measured_at=measured_at)

    @classmethod
    def _collapse(cls, samples: list[SensorSample]) -> list[SensorSample]:
        """A run of identical readings is the instant it began, and nothing more.

        The same rule the live feeds keep: a value re-sent unchanged is not a
        new sample. Without it seventeen days of a steady room would be
        twenty-four thousand rows saying one thing, and the graph would draw
        exactly the line it draws from the seventy that say something.
        """
        result: list[SensorSample] = []
        for sample in samples:
            if not result or result[-1].value != sample.value:
                result.append(sample)
        return result

    def _store(self, sensor_id: int, samples: list[SensorSample]) -> int:
        """Write what is not already there; nothing collected live is overwritten.

        An import fills the past, so a reading the app took itself wins any
        collision - it was measured by this app's own clock, where the file's
        instants are read through an assumption about which one it kept.
        """
        if not samples:
            return 0
        with self._database.transaction():
            for sample in samples:
                self._database.execute(
                    """
                    INSERT INTO samples(sensor_id, measured_at, value) VALUES (%s, %s, %s)
                    ON CONFLICT (sensor_id, measured_at) DO NOTHING
                    """,
                    (sensor_id, sample.measured_at.isoformat(), sample.value),
                )
        return len(samples)

    @classmethod
    def _column(cls, columns: list[str], prefix: str) -> str:
        return next((column for column in columns if column.startswith(prefix)), "")

    @classmethod
    def _device_of(cls, csv_path: Path) -> str:
        """The device an export is named after: "Cave à vin 05_data.csv"."""
        result = csv_path.stem
        if result.endswith(Constants.switchbot_export_suffix):
            result = result[: -len(Constants.switchbot_export_suffix)]
        return result.strip()

    @classmethod
    def _zone(cls, timezone: str) -> ZoneInfo:
        try:
            return ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise AppException(400, f"The time zone {timezone} cannot be resolved.") from None

    @classmethod
    def _instant(cls, text: str, zone: ZoneInfo, previous: datetime | None) -> datetime:
        """One row's moment, read in the house's zone since the file names none.

        A file written in another language is refused rather than guessed at:
        the month is an abbreviation, and one this cannot read would otherwise
        become a plausible wrong date.
        """
        try:
            naive = datetime.strptime(text.strip(), Constants.switchbot_export_date_format)
        except ValueError:
            raise AppException(400, f"{text} is not a date this export should carry.") from None
        result = naive.replace(tzinfo=zone).astimezone(UTC)
        # No offset in the file, so the autumn fall-back repeats an hour and its
        # second pass would land on the first one's instant. The rows are in
        # order: a moment that does not move forward is that second pass.
        if previous is not None and result <= previous:
            shifted = naive.replace(tzinfo=zone, fold=1).astimezone(UTC)
            if shifted > previous:
                result = shifted
        return result

    @classmethod
    def _celsius(cls, degrees: float, fahrenheit: bool) -> float:
        if not fahrenheit:
            return degrees
        return (degrees - Constants.switchbot_fahrenheit_offset) / Constants.switchbot_fahrenheit_factor

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return float(str(raw).strip())
        except ValueError:
            return None
