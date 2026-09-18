from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.commands.sensor_command import SensorCommand
from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.rate_limiter import RateLimiter
from usage.libraries.switch_bot_client import SwitchBotClient
from usage.libraries.switch_bot_hubs import SwitchBotHubs
from usage.structures.app_exception import AppException
from usage.structures.sensor_sample import SensorSample
from usage.structures.sensor_state import SensorState
from usage.structures.settings import Settings
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_feed import SwitchBotFeed
from usage.structures.switch_bot_reading import SwitchBotReading


class SwitchBotSyncCommand:
    """Pulls each house's SwitchBot thermometers out of the cloud, for ever.

    The shape is the water sync's - claim a feed, pull it, write down how it
    went, never raise - with the half that walks a history removed: SwitchBot
    has no history endpoint at all, so a tick is always and only "what does
    everything read now", and a house fed this way starts the day it is added.

    What the cloud will not answer is the two instants Home Assistant answers
    for the other house, and both are worked out here rather than guessed:

    **When did this value last change?** A status carries no instant of its
    own. So it is dated against the last stored sample: an unchanged reading
    keeps the instant it already has - which is what makes a steady room one
    sample rather than a new row every ten minutes - and a changed one is filed
    under this poll. An upper bound, wrong by at most one tick.

    **When was the thermometer last heard from?** The cloud cannot say, and a
    hub replaying a value it cached reads exactly like a live one. So it is
    answered sideways, as the Home Assistant template answers it: whichever of
    the temperature, the humidity and the charge has moved is proof the device
    was heard from, and nothing moving leaves the instant where it was. A lower
    bound, and the safe side of the two - a thermometer whose battery died goes
    grey rather than staying green for ever, and a very steady room goes grey
    early, which is a question rather than a lie.

    Which is why the humidity is collected at all. It is stored as its own
    sensor, hidden, because a percentage has no business on the temperature
    graph - but it moves while a room's temperature holds still, and that is
    exactly when telling a live thermometer from a dead one gets hard.
    """

    def __init__(self, database: Database, settings: Settings, email_sender: EmailSender, limiter: RateLimiter) -> None:
        self._database = database
        self._settings = settings
        self._limiter = limiter
        self._sensors = SensorCommand(database, settings, email_sender)

    def start(self) -> None:
        thread = threading.Thread(target=self._loop, name="switchbot-sync", daemon=True)
        thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exception:  # never let the loop die
                logging.getLogger("usage").warning("[SWITCHBOT] tick failed: %s", exception)
            time.sleep(Constants.switchbot_tick_seconds)

    def tick(self) -> None:
        rows = self._database.fetch_all(
            """
            SELECT id, house_id, token_sealed AS token, secret_sealed AS secret,
                   hub_ids_sealed AS hub_ids, active, event_token_sealed AS event_token, webhook_at
            FROM switchbot_feeds
            WHERE active AND (claimed_until IS NULL OR claimed_until < now())
              AND (last_sync_at IS NULL OR last_sync_at < now() - %s)
            ORDER BY id
            """,
            (timedelta(seconds=Constants.switchbot_sync_seconds),),
        )
        for row in self._database.decrypt_rows(rows, ("token", "secret", "hub_ids", "event_token")):
            feed = self._feed(row)
            if not self._claim(feed.feed_id):
                continue
            try:
                self._sync(feed)
            except AppException as exception:
                self._record(feed.feed_id, exception.message)
            except Exception as exception:  # an unknown failure must not strand the claim
                logging.getLogger("usage").warning("[SWITCHBOT] feed %s failed: %s", feed.feed_id, exception)
                self._record(feed.feed_id, "The import failed unexpectedly.")

    def _sync(self, feed: SwitchBotFeed) -> None:
        """One tick: what the account has, then what each of its devices reads.

        Every device behind the chosen hubs is asked, not only the ones known
        to be thermometers: which is which is answered by whether a status
        carries a temperature, so a model released next year is collected
        without a word of code, and a switch on the same hub costs one call.
        """
        client = SwitchBotClient(feed.token, feed.secret, self._limiter)
        devices = SwitchBotHubs(client.devices()).following(feed.hub_ids)
        if not devices:
            raise AppException(404, "This account has nothing behind the hubs this house follows.")
        now = datetime.now(UTC)
        previous = self._previous(feed.house_id)
        samples: list[SensorSample] = []
        for device in devices:
            reading = self._read(client, device)
            if reading is not None:
                samples.extend(self._samples(device, reading, previous, now))
        if samples:
            self._sensors.store(feed.house_id, samples)
        self._register(client, feed)
        self._record(feed.feed_id, "", bool(samples))

    def _register(self, client: SwitchBotClient, feed: SwitchBotFeed) -> None:
        """Ask SwitchBot once to post this feed's events, and remember that it did.

        Once, not on every tick: a registration that worked stays worked, and
        asking again would spend a call every ten minutes for ever. If SwitchBot
        ever drops it, what shows is the events drying up - which the panel
        reports, since a registration accepted is not the same as one working.

        A feed whose app has no public https address yet is not a failure worth
        a call: it is said plainly and tried again when there is one.
        """
        if feed.webhook_at is not None:
            return
        # A feed set up before any of this existed has no secret to be posted
        # to, so it is minted here rather than left unable to register for ever.
        url = self._event_url(feed.event_token or self._mint(feed.feed_id))
        if not url:
            self._webhook_error(feed.feed_id, "The app has no public https address, so SwitchBot has nowhere to post events.")
            return
        try:
            client.setup_webhook(url)
        except AppException as exception:
            self._webhook_error(feed.feed_id, exception.message)
            return
        self._database.execute(
            "UPDATE switchbot_feeds SET webhook_at = now(), webhook_error = '' WHERE id = %s",
            (feed.feed_id,),
        )

    def _mint(self, feed_id: int) -> str:
        """A secret for this feed's webhook URL, kept so it can be looked up again.

        Sealed as well as hashed, unlike the house's push token: the app has to
        be able to read it back to tell SwitchBot where to post.
        """
        result = secrets.token_urlsafe(Constants.switchbot_event_token_bytes)
        self._database.execute(
            "UPDATE switchbot_feeds SET event_token_sealed = %s, event_token_hash = %s WHERE id = %s",
            (self._database.encrypt(result), self._database.blind_index(result), feed_id),
        )
        return result

    def _event_url(self, event_token: str) -> str:
        """Where SwitchBot posts this feed's events, when the app has an address for it."""
        base = (self._settings.base_url or "").strip().rstrip("/")
        if not base.startswith(Constants.switchbot_webhook_scheme):
            return ""
        return f"{base}{Constants.switchbot_event_path}{event_token}"

    def _webhook_error(self, feed_id: int, message: str) -> None:
        """Kept apart from `last_error`: the readings are arriving either way."""
        self._database.execute(
            "UPDATE switchbot_feeds SET webhook_error = %s WHERE id = %s",
            (message, feed_id),
        )

    def _read(self, client: SwitchBotClient, device: SwitchBotDevice) -> SwitchBotReading | None:
        """One device's reading, or nothing when it has none to give.

        A device the hub could not reach this minute is not a broken feed, and
        neither is a curtain motor sharing the hub with the thermometers: the
        others are still worth having, so both simply drop out of the tick.
        """
        try:
            return client.status(device.device_id)
        except AppException as exception:
            if exception.status_code != Constants.switchbot_unreadable_status:
                raise
            logging.getLogger("usage").info("[SWITCHBOT] device %s unreadable: %s", device.device_id, exception.message)
            return None

    def _samples(
        self,
        device: SwitchBotDevice,
        reading: SwitchBotReading,
        previous: dict[str, SensorState],
        now: datetime,
    ) -> list[SensorSample]:
        """This device's reading as samples, dated against what is already stored."""
        temperature_id = f"{Constants.switchbot_entity_prefix}{device.device_id.lower()}"
        humidity_id = f"{temperature_id}{Constants.switchbot_humidity_suffix}"
        was_temperature = previous.get(self._database.blind_index(temperature_id))
        was_humidity = previous.get(self._database.blind_index(humidity_id))
        temperature = round(reading.temperature, 2)
        humidity = None if reading.humidity is None else round(reading.humidity, 2)
        # Any one of the three moving is proof the device was heard from; none
        # of them moving proves nothing either way, and says so by leaving the
        # instant alone rather than standing in for it with this poll's own.
        heard = (
            self._moved(was_temperature, temperature)
            or self._moved(was_humidity, humidity)
            or self._charged(was_temperature, reading.battery)
        )
        reported_at = now if heard else None
        result = [
            SensorSample(
                entity_id=temperature_id,
                name=device.name or device.device_id,
                unit=Constants.switchbot_temperature_unit,
                value=temperature,
                measured_at=self._instant(was_temperature, temperature, now),
                battery=reading.battery,
                reported_at=reported_at,
            ),
        ]
        if humidity is not None:
            result.append(
                SensorSample(
                    entity_id=humidity_id,
                    name=f"{device.name or device.device_id} humidity",
                    unit=Constants.switchbot_humidity_unit,
                    value=humidity,
                    measured_at=self._instant(was_humidity, humidity, now),
                    reported_at=reported_at,
                    hidden=True,
                ),
            )
        return result

    @classmethod
    def _instant(cls, state: SensorState | None, value: float, now: datetime) -> datetime:
        """When this value started: the stored instant if it has not moved since.

        Keeping it is what makes an unchanged reading the same sample rather
        than a new row every ten minutes, exactly as `last_changed` does for a
        pushed one. A value that has moved is filed under this poll, since the
        only thing known about the change is that it happened since the last.
        """
        if state is None or state.value != value or state.measured_at is None:
            return now
        return state.measured_at

    @classmethod
    def _moved(cls, state: SensorState | None, value: float | None) -> bool:
        """Whether this number has something new to say since it was last stored."""
        if value is None:
            return False
        return state is None or state.value != value

    @classmethod
    def _charged(cls, state: SensorState | None, battery: int | None) -> bool:
        """The charge, which moves rarely and so settles the steadiest of rooms."""
        if battery is None:
            return False
        return state is None or state.battery != battery

    def _previous(self, house_id: int) -> dict[str, SensorState]:
        """The last reading of every sensor of this house, keyed by its entity hash.

        The hash rather than the name: it is a blind index, so the entity id a
        poll is about hashes to the same thing without a single row being
        decrypted. One query for the whole house, asked once per tick.
        """
        rows = self._database.fetch_all(
            """
            SELECT sensors.entity_hash, sensors.battery, last.measured_at, last.value
            FROM sensors
            LEFT JOIN LATERAL (
                SELECT samples.measured_at, samples.value FROM samples
                WHERE samples.sensor_id = sensors.id
                ORDER BY samples.measured_at DESC LIMIT 1
            ) AS last ON true
            WHERE sensors.house_id = %s
            """,
            (house_id,),
        )
        result: dict[str, SensorState] = {}
        for row in rows:
            entity_hash = str(row["entity_hash"])
            result[entity_hash] = SensorState(
                entity_hash=entity_hash,
                value=None if row["value"] is None else float(row["value"]),
                measured_at=row["measured_at"],
                battery=None if row["battery"] is None else int(row["battery"]),
            )
        return result

    def _claim(self, feed_id: int) -> bool:
        claimed = self._database.execute(
            """
            UPDATE switchbot_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
            """,
            (timedelta(minutes=Constants.switchbot_claim_minutes), feed_id),
        )
        return bool(claimed)

    def _record(self, feed_id: int, message: str, stored: bool = False) -> None:
        """Release the claim and say how it went; an empty message means well."""
        self._database.execute(
            """
            UPDATE switchbot_feeds
            SET claimed_until = NULL, last_sync_at = now(), last_error = %s,
                last_point_at = CASE WHEN %s THEN now() ELSE last_point_at END
            WHERE id = %s
            """,
            (message, stored, feed_id),
        )

    @classmethod
    def _feed(cls, row: dict[str, Any]) -> SwitchBotFeed:
        return SwitchBotFeed(
            feed_id=int(row["id"]),
            house_id=int(row["house_id"]),
            token=str(row["token"]),
            secret=str(row["secret"]),
            hub_ids=tuple(part for part in str(row["hub_ids"]).split(",") if part),
            active=bool(row["active"]),
            event_token=str(row["event_token"]),
            webhook_at=row["webhook_at"],
        )
