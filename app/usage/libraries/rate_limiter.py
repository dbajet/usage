from __future__ import annotations

import time
from datetime import timedelta

from usage.constants.constants import Constants
from usage.libraries.database import Database


class RateLimiter:
    """A sliding window of call times, kept in the database so every process shares it.

    A per-minute ceiling is a different creature from a monthly allowance. The
    allowance is spent over weeks and is paced by arithmetic; the ceiling is
    tripped by a single burst and no amount of pacing between ticks prevents
    it, because the burst happens inside one tick. So this sits underneath the
    client and simply will not let the burst out: a call that would be one too
    many waits for the oldest to age out of the window instead.

    The window slides rather than resetting on the minute. A fixed bucket lets
    through twice the ceiling across a boundary - ten calls at 11:59:59 and ten
    more at 12:00:01 - which is exactly the shape of a backfill tick.

    It lives in the database rather than in memory because the ceiling belongs
    to the API key, not to a process, and this app runs as two of them: during
    a blue/green deploy both colours are up at once, and a window each would
    let exactly twice the ceiling through. The database is the only thing the
    two colours share.

    Every time here is `clock_timestamp()` rather than `now()`. `now()` is the
    transaction's start time and holds still for its whole length, and this
    transaction may have spent seconds queueing for the lock: stamping a call
    with the moment its transaction began would age it out of the window before
    it had really been a minute, and let the ceiling drift upwards under load.

    Which makes the count a read-modify-write that two processes can race, so
    it is taken under a Postgres advisory lock held for the length of the
    transaction. Without it both colours read "eight taken", both decide there
    is room, and both go - which is the very thing this class exists to stop.
    The window is also measured by the database's clock for the same reason:
    two servers' clocks agree on nothing else.
    """

    def __init__(self, database: Database, max_calls: int, window_seconds: float) -> None:
        self._database = database
        self._max_calls = max_calls
        self._window_seconds = window_seconds

    def acquire(self, key: str, max_wait_seconds: float) -> bool:
        """Take a slot for this API key, waiting for one if the window is full.

        Returns False rather than waiting for ever, so a caller that somebody is
        sitting in front of - an admin submitting the feed form - gives up and
        says so instead of hanging. The background sync passes a whole window
        and simply sleeps, which costs nothing anybody is watching.
        """
        key_hash = self._database.blind_index(key)
        deadline = time.monotonic() + max_wait_seconds
        while True:
            waiting = self._reserve(key_hash)
            if waiting <= 0:
                return True
            if time.monotonic() + waiting > deadline:
                return False
            time.sleep(waiting)

    def _reserve(self, key_hash: str) -> float:
        """Seconds to wait for a slot, or zero having just taken one.

        Everything here happens inside one transaction and behind one lock, so
        no other process can read the same count and reach the same conclusion.
        """
        window = timedelta(seconds=self._window_seconds)
        with self._database.transaction():
            self._database.fetch_one(
                "SELECT pg_advisory_xact_lock(%s, hashtext(%s)) AS locked",
                (Constants.rate_limit_lock_namespace, key_hash),
            )
            # Only this key's expired rows: a sweep across every key would have
            # two transactions deleting the same rows in different orders, which
            # is a deadlock. Rows belonging to a key nobody uses any more simply
            # sit there, and there are at most a window's worth of them.
            self._database.execute(
                "DELETE FROM api_calls WHERE key_hash = %s AND called_at <= clock_timestamp() - %s",
                (key_hash, window),
            )
            row = self._database.fetch_one(
                """
                SELECT COUNT(*) AS taken,
                       COALESCE(EXTRACT(EPOCH FROM (MIN(called_at) + %s - clock_timestamp())), 0) AS waiting
                FROM api_calls WHERE key_hash = %s
                """,
                (window, key_hash),
            )
            taken = int(row["taken"]) if row is not None else 0
            result = 0.0
            if taken < self._max_calls:
                self._database.execute("INSERT INTO api_calls(key_hash) VALUES (%s)", (key_hash,))
            else:
                # Floored, never zero: a full window that says "wait no time at
                # all" would spin instead of sleeping.
                waiting = float(row["waiting"]) if row is not None else 0.0
                result = max(Constants.rate_limit_retry_seconds, waiting)
            return result
