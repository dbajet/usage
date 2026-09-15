from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.email_texts import EmailTexts
from usage.libraries.eye_on_water_client import EyeOnWaterClient
from usage.structures.app_exception import AppException
from usage.structures.settings import Settings
from usage.structures.water_feed import WaterFeed
from usage.structures.water_leak import WaterLeak
from usage.structures.water_point import WaterPoint


class WaterSyncCommand:
    """Pulls each house's EyeOnWater consumption in the background, for ever.

    EyeOnWater publishes a few hours late and has no documented API, so the
    task is deliberately dull: every quarter of an hour, ask the export for
    the last couple of days - which also repairs the rows EyeOnWater
    re-estimates after the fact - and, until the history has been walked, a
    few month-long chunks going backwards.

    The walk stops after two barren chunks in a row: nobody knows how far
    back a given utility keeps its data, so the only way to learn the floor
    is to hit it. The point of the whole exercise is that once a month is
    stored it never has to be asked for again, whatever the portal does next.

    A feed is claimed before it is pulled (`claimed_until`), so a restart or
    the brief blue/green overlap cannot have two colours importing at once.
    Nothing here is allowed to raise: a failure is written to `last_error`
    and the loop goes round again.
    """

    def __init__(self, database: Database, settings: Settings, email_sender: EmailSender) -> None:
        self._database = database
        self._settings = settings
        self._email_sender = email_sender

    def start(self) -> None:
        thread = threading.Thread(target=self._loop, name="water-sync", daemon=True)
        thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exception:  # never let the loop die
                logging.getLogger("usage").warning("[WATER] tick failed: %s", exception)
            time.sleep(Constants.water_sync_seconds)

    def tick(self) -> None:
        rows = self._database.fetch_all(
            """
            SELECT id, house_id, hostname, username_sealed AS username, password_sealed AS password,
                   meter_uuid_sealed AS meter_uuid, export_unit, active, backfill_from, backfill_done, empty_chunks
            FROM water_feeds
            WHERE active AND (claimed_until IS NULL OR claimed_until < now())
            ORDER BY id
            """,
        )
        for row in self._database.decrypt_rows(rows, ("username", "password", "meter_uuid")):
            feed = self._feed(row)
            if not self._claim(feed.feed_id):
                continue
            try:
                self._sync(feed)
            except AppException as exception:
                self._record(feed.feed_id, exception.message)
            except Exception as exception:  # an unknown failure must not strand the claim
                logging.getLogger("usage").warning("[WATER] feed %s failed: %s", feed.feed_id, exception)
                self._record(feed.feed_id, "The import failed unexpectedly.")

    def _sync(self, feed: WaterFeed) -> None:
        client = self._client(feed)
        today = datetime.now(UTC).date()
        self._store(feed.feed_id, client.export(feed.meter_uuid, today - timedelta(days=Constants.water_recent_days), today))
        walked = feed
        for _ in range(Constants.water_chunks_per_tick):
            if walked.backfill_done:
                break
            walked = self._chunk(client, walked, today)
        self._record(feed.feed_id, "")
        self._leak(feed)

    def _chunk(self, client: EyeOnWaterClient, feed: WaterFeed, today: date) -> WaterFeed:
        """One month further back; two barren ones in a row end the walk."""
        end = feed.backfill_from - timedelta(days=1) if feed.backfill_from is not None else today
        start = end - timedelta(days=Constants.water_chunk_days - 1)
        try:
            stored = self._store(feed.feed_id, client.export(feed.meter_uuid, start, end))
        except AppException as exception:
            if exception.status_code != Constants.water_unreadable_status:
                raise
            # An export we cannot read will not become readable on the next tick.
            # Counting it with the barren months moves the walk past it; retrying
            # it for ever would pin the backfill on one bad month.
            logging.getLogger("usage").warning(
                "[WATER] feed %s: unreadable export for %s to %s", feed.feed_id, start, end,
            )
            stored = 0
        empty_chunks = 0 if stored else feed.empty_chunks + 1
        backfill_done = empty_chunks >= Constants.water_empty_chunks_max
        self._database.execute(
            "UPDATE water_feeds SET backfill_from = %s, empty_chunks = %s, backfill_done = %s WHERE id = %s",
            (start.isoformat(), empty_chunks, backfill_done, feed.feed_id),
        )
        return feed._replace(backfill_from=start, empty_chunks=empty_chunks, backfill_done=backfill_done)

    def _store(self, feed_id: int, points: list[WaterPoint]) -> int:
        if not points:
            return 0
        with self._database.transaction():
            for point in points:
                self._database.execute(
                    """
                    INSERT INTO water_points(feed_id, measured_at, volume, reading, method)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (feed_id, measured_at) DO UPDATE
                    SET volume = EXCLUDED.volume, reading = EXCLUDED.reading, method = EXCLUDED.method
                    """,
                    (feed_id, point.measured_at.isoformat(), point.volume, point.reading, point.method),
                )
            self._database.execute(
                """
                UPDATE water_feeds
                SET last_point_at = (SELECT MAX(measured_at) FROM water_points WHERE feed_id = %s)
                WHERE id = %s
                """,
                (feed_id, feed_id),
            )
        return len(points)

    def _leak(self, feed: WaterFeed) -> None:
        """Report 24 hours that never went quiet, once, when they start."""
        leak = self._continuous_flow(feed.feed_id)
        crossed = self._database.execute(
            "UPDATE water_feeds SET leaking = %s WHERE id = %s AND leaking IS DISTINCT FROM %s RETURNING id",
            (leak is not None, feed.feed_id, leak is not None),
        )
        # Edge triggered, like the thermometers': the crossing is the news, and
        # a leak left unfixed would otherwise mail every quarter of an hour.
        if crossed and leak is not None:
            self._send_leak(feed.house_id, leak)

    def _continuous_flow(self, feed_id: int) -> WaterLeak | None:
        """The last 24 hours of readings, when not one of them is zero.

        A rolling window, not a calendar day: a stretch that runs from one
        afternoon to the next counts exactly as much as one from midnight to
        midnight, and the midnight version would miss it. The window ends at
        the newest reading rather than now, because EyeOnWater publishes hours
        late and a window ending at this instant is always half empty at the
        near end - it would never look complete enough to judge.

        A window that is only partly reported proves nothing, so the readings
        must also be many enough and spread far enough apart to cover it - a
        meter reporting a handful of times a day cannot answer this at all.
        """
        row = self._database.fetch_one(
            """
            SELECT COUNT(*) AS readings, MIN(volume) AS smallest, SUM(volume) AS total,
                   MIN(measured_at) AS oldest, MAX(measured_at) AS newest
            FROM water_points
            WHERE feed_id = %s
              AND measured_at > (SELECT MAX(measured_at) FROM water_points WHERE feed_id = %s) - %s
            """,
            (feed_id, feed_id, timedelta(hours=Constants.water_leak_hours)),
        )
        if row is None or row["oldest"] is None or row["newest"] is None:
            return None
        readings = int(row["readings"])
        hours = (row["newest"] - row["oldest"]).total_seconds() / 3600
        if readings < Constants.water_leak_min_readings or hours < Constants.water_leak_span_hours:
            return None
        if float(row["smallest"]) <= 0:
            return None
        return WaterLeak(
            feed_id=feed_id,
            readings=readings,
            hours=round(hours, 1),
            smallest=float(row["smallest"]),
            total=float(row["total"]),
        )

    def _send_leak(self, house_id: int, leak: WaterLeak) -> None:
        recipients = self._database.fetch_all(
            """
            SELECT users.email_sealed AS email
            FROM water_alerts
            JOIN users ON users.id = water_alerts.user_id
            JOIN user_houses ON user_houses.user_id = water_alerts.user_id
                            AND user_houses.house_id = water_alerts.house_id
            WHERE water_alerts.house_id = %s AND water_alerts.enabled
            ORDER BY water_alerts.user_id
            """,
            (house_id,),
        )
        if not recipients:
            return
        house = self._database.fetch_one("SELECT name_sealed AS name FROM houses WHERE id = %s", (house_id,))
        house_name = self._database.decrypt(str(house["name"])) if house is not None else ""
        subject, body_lines = EmailTexts.water_leak(house_name, leak, self._settings.base_url or "")
        for recipient in recipients:
            email = self._database.decrypt(str(recipient["email"]))
            if not self._email_sender.send(email, subject, body_lines):
                logging.getLogger("usage").warning("[WATER] leak email failed for %s of house %s", email, house_id)

    def _claim(self, feed_id: int) -> bool:
        claimed = self._database.execute(
            """
            UPDATE water_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
            """,
            (timedelta(minutes=Constants.water_claim_minutes), feed_id),
        )
        return bool(claimed)

    def _record(self, feed_id: int, message: str) -> None:
        """Release the claim and say how it went; an empty message means well."""
        self._database.execute(
            "UPDATE water_feeds SET claimed_until = NULL, last_sync_at = now(), last_error = %s WHERE id = %s",
            (message, feed_id),
        )

    @classmethod
    def _client(cls, feed: WaterFeed) -> EyeOnWaterClient:
        return EyeOnWaterClient(feed.hostname, feed.username, feed.password, feed.export_unit)

    @classmethod
    def _feed(cls, row: dict[str, Any]) -> WaterFeed:
        return WaterFeed(
            feed_id=int(row["id"]),
            house_id=int(row["house_id"]),
            hostname=str(row["hostname"]),
            username=str(row["username"]),
            password=str(row["password"]),
            meter_uuid=str(row["meter_uuid"]),
            export_unit=str(row["export_unit"]),
            active=bool(row["active"]),
            backfill_from=row["backfill_from"],
            backfill_done=bool(row["backfill_done"]),
            empty_chunks=int(row["empty_chunks"]),
        )
