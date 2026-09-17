from __future__ import annotations

from datetime import UTC, datetime, timedelta

from usage.libraries.series_pulse import SeriesPulse


def test_stamp() -> None:
    tested = SeriesPulse
    points = [{"at": "2026-09-16T11:00:00+00:00", "volume": 0.0096}]

    # short, and the same answer twice for the same drawing
    result = tested.stamp(points, {"at": "2026-09-16T11:15:00+00:00"})
    assert len(result) == 16
    assert result == tested.stamp(points, {"at": "2026-09-16T11:15:00+00:00"})

    # a value that moved is a different drawing
    moved = [{"at": "2026-09-16T11:00:00+00:00", "volume": 0.0097}]
    assert tested.stamp(moved, {"at": "2026-09-16T11:15:00+00:00"}) != result

    # so is a part that arrived, and the order of the parts is part of it
    assert tested.stamp(points) != result
    assert tested.stamp({"at": "2026-09-16T11:15:00+00:00"}, points) != result

    # a datetime is stamped by what it reads, not by being unhashable
    assert tested.stamp(datetime(2026, 9, 16, tzinfo=UTC)) == tested.stamp(datetime(2026, 9, 16, tzinfo=UTC))
    assert tested.stamp(datetime(2026, 9, 16, tzinfo=UTC)) != tested.stamp(datetime(2026, 9, 17, tzinfo=UTC))

    # nothing at all is still an answer
    assert len(tested.stamp()) == 16


def test_next_poll() -> None:
    tested = SeriesPulse
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    ahead = lambda seconds: now + timedelta(seconds=seconds)  # noqa: E731

    # the earliest of the sources decides, and a source with nothing to say is skipped
    assert tested.next_poll([ahead(599), ahead(3000)], now) == 599
    assert tested.next_poll([None, ahead(59)], now) == 59
    assert tested.next_poll([ahead(3000), None], now) == 900

    # a feed nobody can date at all waits the ceiling rather than asking at once
    assert tested.next_poll([], now) == 900
    assert tested.next_poll([None, None], now) == 900

    # an overdue feed is held at the floor: zero would be a spin
    assert tested.next_poll([ahead(-3600)], now) == 30
    assert tested.next_poll([now], now) == 30

    # and one whose pull is a day away is still looked in on
    assert tested.next_poll([ahead(86400)], now) == 900

    # the seconds are whole, and rounded towards asking sooner
    assert tested.next_poll([ahead(60.9)], now) == 60
