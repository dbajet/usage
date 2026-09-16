from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

from usage.libraries.rate_limiter import RateLimiter

SQL_LOCK = "SELECT pg_advisory_xact_lock(%s, hashtext(%s)) AS locked"
SQL_PRUNE = "DELETE FROM api_calls WHERE key_hash = %s AND called_at <= clock_timestamp() - %s"
SQL_COUNT = """
                SELECT COUNT(*) AS taken,
                       COALESCE(EXTRACT(EPOCH FROM (MIN(called_at) + %s - clock_timestamp())), 0) AS waiting
                FROM api_calls WHERE key_hash = %s
                """
SQL_TAKE = "INSERT INTO api_calls(key_hash) VALUES (%s)"
WINDOW = timedelta(seconds=60.0)


def helper_instance(max_calls: int = 9, window_seconds: float = 60.0) -> RateLimiter:
    return RateLimiter(MagicMock(), max_calls, window_seconds)


def test___init__() -> None:
    database = MagicMock()
    tested = RateLimiter(database, 9, 60.0)
    assert tested._database is database
    assert tested._max_calls == 9
    assert tested._window_seconds == 60.0
    assert database.mock_calls == []


@patch("usage.libraries.rate_limiter.time")
@patch.object(RateLimiter, "_reserve")
def test_acquire(reserve: MagicMock, mock_time: MagicMock) -> None:
    tested = helper_instance()
    database = tested._database

    def reset_mocks() -> None:
        reserve.reset_mock()
        mock_time.reset_mock()
        database.reset_mock()

    # the raw key never reaches the table: it is blind indexed like any secret
    exp_database = [call.blind_index("theApiKey")]

    # room under the ceiling: through without sleeping at all
    database.blind_index.side_effect = ["hashedKey"]
    mock_time.monotonic.side_effect = [1000.0]
    reserve.side_effect = [0.0]
    result = tested.acquire("theApiKey", 60.0)
    assert result is True
    assert reserve.mock_calls == [call("hashedKey")]
    assert mock_time.mock_calls == [call.monotonic()]
    assert database.mock_calls == exp_database
    reset_mocks()

    # the window is full: wait for the oldest call to age out, then go
    database.blind_index.side_effect = ["hashedKey"]
    mock_time.monotonic.side_effect = [1000.0, 1000.0]
    reserve.side_effect = [5.0, 0.0]
    result = tested.acquire("theApiKey", 60.0)
    assert result is True
    assert reserve.mock_calls == [call("hashedKey"), call("hashedKey")]
    exp_calls = [call.monotonic(), call.monotonic(), call.sleep(5.0)]
    assert mock_time.mock_calls == exp_calls
    assert database.mock_calls == exp_database
    reset_mocks()

    # the wait runs past what the caller can give it: refused rather than hung
    database.blind_index.side_effect = ["hashedKey"]
    mock_time.monotonic.side_effect = [1000.0, 1000.0]
    reserve.side_effect = [30.0]
    result = tested.acquire("theApiKey", 10.0)
    assert result is False
    assert reserve.mock_calls == [call("hashedKey")]
    assert mock_time.mock_calls == [call.monotonic(), call.monotonic()]
    assert database.mock_calls == exp_database
    reset_mocks()


def test__reserve() -> None:
    tested = helper_instance(9, 60.0)
    database = tested._database

    def reset_mocks() -> None:
        database.reset_mock()

    # the lock, the prune and the count all happen inside one transaction, so no
    # other colour can read the same count and reach the same conclusion
    exp_head: list[Any] = [
        call.transaction(),
        call.transaction().__enter__(),
        call.fetch_one(SQL_LOCK, (8421, "hashedKey")),
        call.execute(SQL_PRUNE, ("hashedKey", WINDOW)),
        call.fetch_one(SQL_COUNT, (WINDOW, "hashedKey")),
    ]

    # room to spare: the slot is taken there and then
    database.fetch_one.side_effect = [None, {"taken": 3, "waiting": Decimal("42.5")}]
    database.execute.side_effect = [0, 0]
    result = tested._reserve("hashedKey")
    assert result == 0.0
    exp_calls = [*exp_head, call.execute(SQL_TAKE, ("hashedKey",)), call.transaction().__exit__(None, None, None)]
    assert database.mock_calls == exp_calls
    reset_mocks()

    # the last slot is still a slot
    database.fetch_one.side_effect = [None, {"taken": 8, "waiting": Decimal("1.0")}]
    database.execute.side_effect = [0, 0]
    result = tested._reserve("hashedKey")
    assert result == 0.0
    assert database.mock_calls == exp_calls
    reset_mocks()

    # full: wait out whatever is left of the oldest call's minute, and take nothing
    database.fetch_one.side_effect = [None, {"taken": 9, "waiting": Decimal("12.25")}]
    database.execute.side_effect = [0]
    result = tested._reserve("hashedKey")
    assert result == 12.25
    assert database.mock_calls == [*exp_head, call.transaction().__exit__(None, None, None)]
    reset_mocks()

    # full but the arithmetic says no wait at all: floored, or the loop would spin
    for waiting in [Decimal("0"), Decimal("-3")]:
        database.fetch_one.side_effect = [None, {"taken": 9, "waiting": waiting}]
        database.execute.side_effect = [0]
        result = tested._reserve("hashedKey")
        assert result == 0.05
        assert database.mock_calls == [*exp_head, call.transaction().__exit__(None, None, None)]
        reset_mocks()

    # the count came back empty: an empty window, so the slot is free
    database.fetch_one.side_effect = [None, None]
    database.execute.side_effect = [0, 0]
    result = tested._reserve("hashedKey")
    assert result == 0.0
    assert database.mock_calls == exp_calls
    reset_mocks()
