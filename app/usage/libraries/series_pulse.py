from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Iterable

from usage.constants.constants import Constants


class SeriesPulse:
    """The two answers a Realtime series carries beside its points: is this the
    same as last time, and when could it stop being?

    Both exist for one reason. The page used to ask for three graphs a minute
    and redraw all of them whether or not a single number had moved, which is
    a flicker on every tick and a round of queries behind it. The stamp lets
    the browser skip a redraw that would change nothing; the hint lets it stop
    asking at all until the feed behind the graph could have something new.

    Neither is a promise. The stamp says the drawn values are identical, not
    that the world is; the hint says when a source could next answer, not that
    it will.
    """

    @classmethod
    def stamp(cls, *parts: Any) -> str:
        """A short fingerprint of everything one card draws.

        The window's own end is deliberately left out of it by every caller:
        `until` is "now", so it moves on every single request, and folding it
        in would make each answer look new while the graph it draws is
        identical to the pixel.
        """
        payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[: Constants.realtime_stamp_length]

    @classmethod
    def next_poll(cls, due: Iterable[datetime | None], now: datetime) -> int:
        """Seconds until the earliest source behind this graph could have moved.

        Held at both ends. A feed that is already overdue would otherwise ask
        for zero and turn the page into a spin, and one whose next pull is
        hours away is still looked in on, because an import, a hand on the
        refresh button and a backfill all put rows in the window that no
        schedule predicted.
        """
        moments = [moment for moment in due if moment is not None]
        if not moments:
            return Constants.realtime_poll_max_seconds
        ahead = (min(moments) - now).total_seconds()
        return int(min(Constants.realtime_poll_max_seconds, max(Constants.realtime_poll_min_seconds, ahead)))
