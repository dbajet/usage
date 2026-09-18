from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage.libraries.database import Database
from usage.structures.app_exception import AppException


class SeriesZone:
    """Which clock a Realtime graph is cut and labelled on.

    Readings are stored as instants and always will be: a stored moment that
    moves when a clock does is the one bug none of this could recover from. But
    a graph is read by somebody standing somewhere, and the two obvious answers
    disagree. A house in France watched from California has its coldest hour
    drawn in the previous evening, and a day bucketed on UTC is neither
    watcher's day - it runs from 02:00 in Paris and from 17:00 in California.

    So the page says which clock it wants and this is what proves the answer is
    a real one. The zone reaches the query as well as the labels, because a
    bucket cut on one clock and labelled on another is worse than either: the
    bars would be honest and the axis would lie about them.

    Binning happens on the local timeline - the reading is converted, binned,
    and converted back - rather than by an offset from a fixed origin. An
    offset is right for half the year: `date_bin` steps in fixed intervals and
    knows nothing about the hour a zone gives back in October, so a day cut
    that way drifts an hour every spring.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def of(self, wanted: str, house_id: int) -> str:
        """The zone to draw in, which is the page's ask unless it is not a zone.

        The fallback is the house's own, so a page that says nothing - or an
        older one that does not know to - still gets a graph cut where the
        instruments stand rather than on UTC.
        """
        if self.known(wanted.strip()):
            return wanted.strip()
        row = self._database.fetch_one("SELECT timezone FROM houses WHERE id = %s", (house_id,))
        fallback = str(row["timezone"] or "") if row is not None else ""
        if self.known(fallback):
            return fallback
        raise AppException(400, f"Neither {wanted} nor the house's own zone is one this server knows.")

    @classmethod
    def known(cls, name: str) -> bool:
        if not name:
            return False
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return False
        return True
