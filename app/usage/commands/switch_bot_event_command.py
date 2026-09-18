from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.commands.sensor_command import SensorCommand
from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.settings import Settings
from usage.structures.switch_bot_event import SwitchBotEvent


class SwitchBotEventCommand:
    """SwitchBot's own account of a reading, posted as it happens.

    This is the only thing in the app that knows when a reading was actually
    taken. Home Assistant knows it for the house it watches; a polled status
    carries no instant at all, so the sync has to date a change to somewhere
    inside its own ten minutes and can only infer that a device is still alive.
    A `changeReport` carries `timeOfSample`, which answers both exactly.

    It does not replace the polling and is not meant to. Events fire on change,
    so a room holding one number reports nothing for hours; the app can be down
    when one is sent, and nothing is re-sent. The sync is what makes a feed
    whole, and this is what makes it sharp - and the two agree by construction,
    because a sample is keyed by the instant its value changed: the poll that
    follows an event finds the value unchanged and keeps the event's instant
    rather than writing its own, coarser one.

    Nothing signs the POST - SwitchBot documents no signature for it at all - so
    two things stand in for one. The URL carries a secret nobody else has, and
    **no event may create a sensor**: the device has to be one this house
    already collects, or the event is dropped. Without that second rule the
    account's other house would quietly grow a set of thermometers here, since
    a webhook reports every device on the account and cannot be narrowed.
    """

    def __init__(self, database: Database, settings: Settings, email_sender: EmailSender) -> None:
        self._database = database
        self._sensors = SensorCommand(database, settings, email_sender)

    def ingest(self, event_token: str, data: dict[str, Any]) -> dict[str, int]:
        """One event, for a device this house already knows, or nothing at all."""
        feed = self._feed(event_token)
        if str(data.get("eventType") or "") != Constants.switchbot_event_change:
            return {"accepted": 0}
        event = self._event(dict(data.get("context") or {}))
        if event is None:
            return {"accepted": 0}
        house_id = int(feed["house_id"])
        stored = self._sensors.store(house_id, self._samples(event), create=False)
        # Only once something was written: an event for another house's
        # thermometer proves this feed is registered, but says nothing about
        # whether this house is being told anything.
        if stored["accepted"]:
            self._database.execute(
                "UPDATE switchbot_feeds SET last_event_at = now() WHERE id = %s",
                (int(feed["id"]),),
            )
        return {"accepted": stored["accepted"]}

    def _feed(self, event_token: str) -> dict[str, Any]:
        result = self._database.fetch_one(
            "SELECT id, house_id FROM switchbot_feeds WHERE event_token_hash = %s AND active",
            (self._database.blind_index(event_token),),
        )
        if result is None:
            # The same answer a wrong URL gets anywhere: nothing here says
            # whether the secret was close.
            raise AppException(404, "Not found.")
        return result

    def _samples(self, event: SwitchBotEvent) -> list[SensorSample]:
        """The event as the samples a poll would have written, dated exactly.

        `reported_at` is the same instant rather than an inference: the device
        said this, and said when. The humidity rides along hidden, as it does
        on the polled path, so the two write the same pair of sensors.
        """
        entity_id = f"{Constants.switchbot_entity_prefix}{event.device_id.lower()}"
        result = [
            SensorSample(
                entity_id=entity_id,
                name=entity_id,
                unit=Constants.switchbot_temperature_unit,
                value=round(event.temperature, 2),
                measured_at=event.measured_at,
                battery=event.battery,
                reported_at=event.measured_at,
            ),
        ]
        if event.humidity is not None:
            result.append(
                SensorSample(
                    entity_id=f"{entity_id}{Constants.switchbot_humidity_suffix}",
                    name=entity_id,
                    unit=Constants.switchbot_humidity_unit,
                    value=round(event.humidity, 2),
                    measured_at=event.measured_at,
                    reported_at=event.measured_at,
                    hidden=True,
                ),
            )
        return result

    def _event(self, context: dict[str, Any]) -> SwitchBotEvent | None:
        """A meter's reading out of the payload, or nothing when it is not one."""
        device_id = str(context.get("deviceMac") or "").strip()
        temperature = self._number(context.get("temperature"))
        if not device_id or temperature is None:
            return None
        battery = self._number(context.get("battery"))
        return SwitchBotEvent(
            device_id=device_id,
            temperature=self._celsius(temperature, str(context.get("scale") or "")),
            measured_at=self._instant(context.get("timeOfSample")),
            humidity=self._number(context.get("humidity")),
            battery=None if battery is None else int(round(battery)),
        )

    @classmethod
    def _celsius(cls, temperature: float, scale: str) -> float:
        """Everything is stored in the unit a status call answers in."""
        if scale.strip().upper() != Constants.switchbot_scale_fahrenheit:
            return temperature
        return (temperature - Constants.switchbot_fahrenheit_offset) / Constants.switchbot_fahrenheit_factor

    @classmethod
    def _instant(cls, raw: Any) -> datetime:
        """`timeOfSample`, read as milliseconds unless it can only be seconds.

        The field is documented by an example rather than by a unit, and the two
        readings are a factor of a thousand apart: seconds read as milliseconds
        land in 1970, and the graph would keep a point there for ever. So a
        value too small to be milliseconds is taken as seconds, and anything
        that still lands outside a plausible window is not trusted at all - the
        arrival stands in for it, exactly as it would for an event with no
        instant on it.
        """
        now = datetime.now(UTC)
        stamp = cls._number(raw)
        if stamp is None:
            return now
        seconds = stamp if abs(stamp) < Constants.switchbot_epoch_millis_floor else stamp / 1000
        try:
            result = datetime.fromtimestamp(seconds, UTC)
        except (OSError, OverflowError, ValueError):
            return now
        if result > now + timedelta(seconds=Constants.switchbot_event_future_seconds):
            return now
        if result < now - timedelta(days=Constants.switchbot_event_past_days):
            logging.getLogger("usage").info("[SWITCHBOT] event stamped %s, taken as now", result.isoformat())
            return now
        return result

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
