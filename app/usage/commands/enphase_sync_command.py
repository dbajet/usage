from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.enphase_client import EnphaseClient
from usage.libraries.rate_limiter import RateLimiter
from usage.structures.app_exception import AppException
from usage.structures.enphase_feed import EnphaseFeed
from usage.structures.enphase_point import EnphasePoint
from usage.structures.enphase_tokens import EnphaseTokens


class EnphaseSyncCommand:
    """Pulls each house's Enphase system in the background, for ever.

    The shape is the water sync's - claim a feed, pull it, write down how it
    went, never raise - but the economics are the opposite way round. The water
    portal is free and slow to publish, so that feed asks often and cheaply.
    Enphase answers in minutes and charges for every question, so this one is
    paced by what is left of the plan's monthly allowance: a feed with a
    thousand calls a month and twenty days to go works out its own interval
    rather than running hourly and going silent three weeks early.

    History is walked at two resolutions because they cost such different
    amounts. The daily pass is two calls for the whole life of the system and
    so runs to the end on the first tick. The quarter-hourly pass is three
    calls for every single day it covers, so it walks back a fortnight - enough
    to fill the day and the week views - and then stops for good.

    The one thing here that must not fail is keeping the tokens: Enphase
    rotates the refresh token on every use, so the pair in the database is the
    only copy and the previous one is already dead. They are written back
    whether the pull succeeded or not, which is why the save sits in a
    `finally` rather than on the happy path.
    """

    def __init__(self, database: Database, limiter: RateLimiter) -> None:
        self._database = database
        self._limiter = limiter

    def start(self) -> None:
        thread = threading.Thread(target=self._loop, name="enphase-sync", daemon=True)
        thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exception:  # never let the loop die
                logging.getLogger("usage").warning("[ENPHASE] tick failed: %s", exception)
            time.sleep(Constants.enphase_tick_seconds)

    def tick(self) -> None:
        rows = self._database.fetch_all(
            """
            SELECT id, house_id, client_id_sealed AS client_id, client_secret_sealed AS client_secret,
                   api_key_sealed AS api_key, system_id_sealed AS system_id,
                   access_token_sealed AS access_token, refresh_token_sealed AS refresh_token,
                   token_expires_at, active, backfill_from, backfill_done, fine_from, fine_done,
                   calls_used, calls_budget, calls_month, production_path, last_sync_at
            FROM enphase_feeds
            WHERE active AND source = %s AND (claimed_until IS NULL OR claimed_until < now())
            ORDER BY id
            """,
            (Constants.enphase_source_cloud,),
        )
        sealed = ("client_id", "client_secret", "api_key", "system_id", "access_token", "refresh_token")
        for row in self._database.decrypt_rows(rows, sealed):
            feed = self._feed(row)
            if not self._is_due(feed, row["last_sync_at"]):
                continue
            if not self._claim(feed.feed_id):
                continue
            self._run(feed)

    def _run(self, feed: EnphaseFeed) -> None:
        """Pull one feed, and write back the tokens whatever happens to it."""
        client = self._client(feed)
        message = ""
        try:
            self._sync(client, feed)
        except AppException as exception:
            message = exception.message
        except Exception as exception:  # an unknown failure must not strand the claim
            logging.getLogger("usage").warning("[ENPHASE] feed %s failed: %s", feed.feed_id, exception)
            message = "The import failed unexpectedly."
        finally:
            # A rotated refresh token is the only one that still works: losing it
            # because the pull failed afterwards would lock the feed out for good.
            self._save_tokens(feed, client.tokens)
            self._save_production_path(feed, client.production_path)
            self._record(feed.feed_id, message, client.calls)

    def _sync(self, client: EnphaseClient, feed: EnphaseFeed) -> None:
        """One tick: the recent days, the daily history, then a little of the fine walk.

        A first tick asks for far more than the per-minute ceiling allows - six
        calls for the recent days, two for the history, three per day of the
        fine walk - and deliberately makes no attempt to stay under it here.
        Spreading the work over ticks instead would starve the backfill, since
        ticks are hours apart and the ceiling's window is a minute: the walk
        would never get a turn. The limiter underneath the client holds the
        burst back call by call, so this stays readable and the tick simply
        takes a few minutes the first time.
        """
        today = datetime.now(UTC).date()
        for day in self._recent_days(today):
            self._store(feed.feed_id, self._day(client, feed.system_id, day))
        walked = feed if feed.backfill_done else self._history(client, feed, today)
        for _ in range(Constants.enphase_fine_days_per_tick):
            if walked.fine_done:
                break
            walked = self._fine_chunk(client, walked, today)

    @classmethod
    def _recent_days(cls, today: date) -> list[date]:
        """Today and the days just behind it, re-asked on every tick.

        Enphase revises the last intervals of a day once the meters have all
        reported, so re-asking is not waste: it is what repairs them.
        """
        return [today - timedelta(days=offset) for offset in range(Constants.enphase_recent_days)]

    @classmethod
    def _day(cls, client: EnphaseClient, system_id: str, day: date) -> list[EnphasePoint]:
        """The three streams of one day, as one list to be merged on the instant."""
        return [
            *client.production(system_id, day),
            *client.consumption(system_id, day),
            *client.battery(system_id, day),
        ]

    def _history(self, client: EnphaseClient, feed: EnphaseFeed, today: date) -> EnphaseFeed:
        """The daily totals of the system's whole life, in two calls, once."""
        try:
            self._store(feed.feed_id, client.daily(feed.system_id, None, today))
        except AppException as exception:
            if exception.status_code != Constants.enphase_unreadable_status:
                raise
            # Unreadable today means unreadable on every tick: marking it done
            # spends two calls once instead of two calls for ever.
            logging.getLogger("usage").warning("[ENPHASE] feed %s: unreadable history", feed.feed_id)
        self._database.execute(
            "UPDATE enphase_feeds SET backfill_done = true, backfill_from = %s WHERE id = %s",
            (today.isoformat(), feed.feed_id),
        )
        return feed._replace(backfill_done=True, backfill_from=today)

    def _fine_chunk(self, client: EnphaseClient, feed: EnphaseFeed, today: date) -> EnphaseFeed:
        """One more day of quarter-hourly history, until the fortnight is covered."""
        day = feed.fine_from - timedelta(days=1) if feed.fine_from is not None else today
        try:
            self._store(feed.feed_id, self._day(client, feed.system_id, day))
        except AppException as exception:
            if exception.status_code != Constants.enphase_unreadable_status:
                raise
            logging.getLogger("usage").warning("[ENPHASE] feed %s: unreadable telemetry for %s", feed.feed_id, day)
        fine_done = day <= today - timedelta(days=Constants.enphase_fine_days)
        self._database.execute(
            "UPDATE enphase_feeds SET fine_from = %s, fine_done = %s WHERE id = %s",
            (day.isoformat(), fine_done, feed.feed_id),
        )
        return feed._replace(fine_from=day, fine_done=fine_done)

    def _store(self, feed_id: int, points: list[EnphasePoint]) -> int:
        """Merge the streams on the instant: each one fills in its own column."""
        if not points:
            return 0
        with self._database.transaction():
            for point in points:
                self._database.execute(
                    """
                    INSERT INTO enphase_points(feed_id, measured_at, span_minutes, production, consumption, battery_level)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (feed_id, measured_at, span_minutes) DO UPDATE
                    SET production = COALESCE(EXCLUDED.production, enphase_points.production),
                        consumption = COALESCE(EXCLUDED.consumption, enphase_points.consumption),
                        battery_level = COALESCE(EXCLUDED.battery_level, enphase_points.battery_level)
                    """,
                    (
                        feed_id,
                        point.measured_at.isoformat(),
                        point.span_minutes,
                        point.production,
                        point.consumption,
                        point.battery_level,
                    ),
                )
            self._database.execute(
                """
                UPDATE enphase_feeds
                SET last_point_at = (SELECT MAX(measured_at) FROM enphase_points WHERE feed_id = %s)
                WHERE id = %s
                """,
                (feed_id, feed_id),
            )
        return len(points)

    def _is_due(self, feed: EnphaseFeed, last_sync_at: datetime | None) -> bool:
        if last_sync_at is None:
            return True
        return datetime.now(UTC) - last_sync_at >= timedelta(seconds=self.pace(feed))

    @classmethod
    def pace(cls, feed: EnphaseFeed) -> int:
        """Seconds between pulls, so the month's allowance lasts the month.

        A plan's allowance is monthly and the free one is small, so the useful
        question is not "how fresh could this be" but "how many more times can
        this feed afford to ask before the month turns". Spending it evenly
        beats running hourly until the eighth and then showing nothing at all.

        An exhausted budget waits for the turn of the month rather than
        hammering a door that answers 429.
        """
        now = datetime.now(UTC)
        remaining = cls._seconds_left(now)
        left = cls._calls_left(feed, now.date())
        if left <= 0:
            return int(remaining)
        ticks = max(1.0, left / (Constants.enphase_recent_days * Constants.enphase_streams))
        return int(min(Constants.enphase_sync_max_seconds, max(Constants.enphase_sync_min_seconds, remaining / ticks)))

    @classmethod
    def _calls_left(cls, feed: EnphaseFeed, today: date) -> int:
        """What is left of this month; a feed last counted in an older month starts afresh."""
        budget = feed.calls_budget or Constants.enphase_calls_budget
        if feed.calls_month is None or (feed.calls_month.year, feed.calls_month.month) != (today.year, today.month):
            return budget
        return budget - feed.calls_used

    @classmethod
    def _seconds_left(cls, now: datetime) -> float:
        """Until the first instant of next month, when the allowance comes back."""
        year = now.year + (now.month == 12)
        month = 1 if now.month == 12 else now.month + 1
        return max(1.0, (datetime(year, month, 1, tzinfo=UTC) - now).total_seconds())

    def _save_tokens(self, feed: EnphaseFeed, tokens: EnphaseTokens) -> None:
        if (tokens.access_token, tokens.refresh_token) == (feed.access_token, feed.refresh_token):
            return
        self._database.execute(
            """
            UPDATE enphase_feeds
            SET access_token_sealed = %s, refresh_token_sealed = %s, token_expires_at = %s
            WHERE id = %s
            """,
            (
                self._database.encrypt(tokens.access_token),
                self._database.encrypt(tokens.refresh_token),
                tokens.expires_at.isoformat() if tokens.expires_at is not None else None,
                feed.feed_id,
            ),
        )

    def _save_production_path(self, feed: EnphaseFeed, path: str) -> None:
        """Keep what the pull found out, so nothing has to find it out again."""
        if path == feed.production_path or not path:
            return
        self._database.execute(
            "UPDATE enphase_feeds SET production_path = %s WHERE id = %s",
            (path, feed.feed_id),
        )

    def _claim(self, feed_id: int) -> bool:
        claimed = self._database.execute(
            """
            UPDATE enphase_feeds SET claimed_until = now() + %s
            WHERE id = %s AND (claimed_until IS NULL OR claimed_until < now())
            RETURNING id
            """,
            (timedelta(minutes=Constants.enphase_claim_minutes), feed_id),
        )
        return bool(claimed)

    def _record(self, feed_id: int, message: str, calls: int) -> None:
        """Release the claim, say how it went, and bill the calls to this month."""
        self._database.execute(
            """
            UPDATE enphase_feeds
            SET claimed_until = NULL, last_sync_at = now(), last_error = %s,
                calls_used = CASE
                    WHEN calls_month = date_trunc('month', now())::date THEN calls_used + %s
                    ELSE %s END,
                calls_month = date_trunc('month', now())::date
            WHERE id = %s
            """,
            (message, calls, calls, feed_id),
        )

    def _client(self, feed: EnphaseFeed) -> EnphaseClient:
        return EnphaseClient(
            feed.client_id,
            feed.client_secret,
            feed.api_key,
            EnphaseTokens(
                access_token=feed.access_token,
                refresh_token=feed.refresh_token,
                expires_at=feed.token_expires_at,
            ),
            self._limiter,
            feed.production_path,
        )

    @classmethod
    def _feed(cls, row: dict[str, Any]) -> EnphaseFeed:
        return EnphaseFeed(
            feed_id=int(row["id"]),
            house_id=int(row["house_id"]),
            client_id=str(row["client_id"]),
            client_secret=str(row["client_secret"]),
            api_key=str(row["api_key"]),
            system_id=str(row["system_id"]),
            access_token=str(row["access_token"]),
            refresh_token=str(row["refresh_token"]),
            token_expires_at=row["token_expires_at"],
            active=bool(row["active"]),
            backfill_from=row["backfill_from"],
            backfill_done=bool(row["backfill_done"]),
            fine_from=row["fine_from"],
            fine_done=bool(row["fine_done"]),
            calls_used=int(row["calls_used"]),
            calls_budget=int(row["calls_budget"]),
            calls_month=row["calls_month"],
            production_path=str(row["production_path"]),
        )
