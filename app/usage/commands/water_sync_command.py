from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.eye_on_water_client import EyeOnWaterClient
from usage.structures.app_exception import AppException
from usage.structures.water_feed import WaterFeed
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

    def __init__(self, database: Database) -> None:
        self._database = database

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
