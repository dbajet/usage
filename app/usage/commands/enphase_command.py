from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.enphase_client import EnphaseClient
from usage.libraries.rate_limiter import RateLimiter
from usage.libraries.series_pulse import SeriesPulse
from usage.structures.app_exception import AppException
from usage.structures.enphase_system import EnphaseSystem
from usage.structures.enphase_tokens import EnphaseTokens
from usage.structures.session_user import SessionUser


class EnphaseCommand:
    """The Enphase feeds of a house, and the solar data they have collected.

    A feed is one system of one Enphase developer application. Three secrets
    identify the application and a fourth, short-lived one authorises it: the
    admin pastes the code Enphase shows after they approve the application in
    their browser, and it is exchanged for a token pair here and now. Codes
    expire within minutes, which is why the exchange happens while the form is
    still open rather than on the next tick of the background sync.

    The system id is asked of the account rather than copied by hand, for the
    same reason the water meter's uuid is: a number that is wrong answers with
    an empty day rather than a refusal, and an empty day looks exactly like bad
    weather.

    Everything is stored in kilowatt-hours, as the rest of the app stores
    electricity. Production and consumption are counters and so are summed per
    bucket; the battery is a level and is averaged.
    """

    def __init__(self, database: Database, limiter: RateLimiter) -> None:
        self._database = database
        self._limiter = limiter

    def authorize_url(self, user: SessionUser, client_id: str) -> dict[str, str]:
        """Where the admin sends their browser to approve the application."""
        self._require_admin(user)
        if not client_id.strip():
            raise AppException(400, "Enter the application's client id first.")
        return {"url": EnphaseClient.authorize_url(client_id.strip())}

    def list_feeds(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_admin(user)
        self._require_house(user, house_id)
        feeds = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, client_id_sealed AS client_id, system_id_sealed AS system_id, active,
                       last_sync_at, last_point_at, last_error, backfill_done, fine_from, fine_done,
                       calls_used, calls_budget, calls_month, token_expires_at
                FROM enphase_feeds WHERE house_id = %s AND source = %s ORDER BY id
                """,
                (house_id, Constants.enphase_source_cloud),
            ),
            ("client_id", "system_id"),
        )
        result: list[dict[str, Any]] = []
        for feed in feeds:
            counts = self._database.fetch_one(
                "SELECT COUNT(*) AS points, MIN(measured_at) AS first_at FROM enphase_points WHERE feed_id = %s",
                (int(feed["id"]),),
            )
            result.append(
                {
                    "id": int(feed["id"]),
                    "client_id": str(feed["client_id"]),
                    "system_id": str(feed["system_id"]),
                    "active": bool(feed["active"]),
                    "last_sync_at": self._moment(feed["last_sync_at"]),
                    "last_point_at": self._moment(feed["last_point_at"]),
                    "last_error": str(feed["last_error"]),
                    "backfill_done": bool(feed["backfill_done"]),
                    "fine_done": bool(feed["fine_done"]),
                    "fine_from": str(feed["fine_from"] or ""),
                    "calls_used": int(feed["calls_used"]),
                    "calls_budget": int(feed["calls_budget"]),
                    "calls_month": str(feed["calls_month"] or ""),
                    "token_expires_at": self._moment(feed["token_expires_at"]),
                    "points": int(counts["points"]) if counts is not None else 0,
                    "first_point_at": self._moment(counts["first_at"]) if counts is not None else "",
                },
            )
        return {"feeds": result, "live": self._live(house_id), "local": self._local(house_id)}

    def create_feed(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        house_id = int(data.get("house_id") or 0)
        self._require_admin(user)
        self._require_house(user, house_id)
        client_id = str(data.get("client_id") or "").strip()
        client_secret = str(data.get("client_secret") or "").strip()
        api_key = str(data.get("api_key") or "").strip()
        code = str(data.get("code") or "").strip()
        if not client_id or not client_secret or not api_key:
            raise AppException(400, "Enter the application's client id, client secret and API key.")
        if not code:
            raise AppException(400, "Authorise the application first, then paste the code Enphase shows you.")
        client = EnphaseClient(client_id, client_secret, api_key, None, self._limiter)
        tokens = client.exchange(code)
        system_id = self._resolve_system(client, self._system_id(data))
        self._probe(client, system_id)
        existing = self._database.fetch_one(
            "SELECT id FROM enphase_feeds WHERE house_id = %s AND system_id_hash = %s",
            (house_id, self._database.blind_index(system_id)),
        )
        if existing is not None:
            raise AppException(409, "This system is already collected for this house.")
        feed_id = self._database.execute(
            """
            INSERT INTO enphase_feeds(house_id, client_id_sealed, client_secret_sealed, api_key_sealed,
                                      system_id_sealed, system_id_hash, access_token_sealed,
                                      refresh_token_sealed, token_expires_at, calls_budget, production_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                self._database.encrypt(client_id),
                self._database.encrypt(client_secret),
                self._database.encrypt(api_key),
                self._database.encrypt(system_id),
                self._database.blind_index(system_id),
                self._database.encrypt(tokens.access_token),
                self._database.encrypt(tokens.refresh_token),
                tokens.expires_at.isoformat() if tokens.expires_at is not None else None,
                self._budget(data),
                # The probe has just asked for a day of production, so it already
                # knows which endpoint answers here: the sync need not find out.
                client.production_path,
            ),
        )
        return {"id": feed_id, "message": "Enphase feed added. The first import starts within a minute."}

    def update_feed(self, user: SessionUser, feed_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        feed = self._require_feed(user, feed_id)
        client_id = str(data.get("client_id") or "").strip()
        api_key = str(data.get("api_key") or "").strip() or self._database.decrypt(str(feed["api_key"]))
        if not client_id:
            raise AppException(400, "Enter the application's client id.")
        # Empty means "keep the one already stored": neither is ever sent back out.
        client_secret = str(data.get("client_secret") or "").strip() or self._database.decrypt(str(feed["client_secret"]))
        code = str(data.get("code") or "").strip()
        tokens = self._reauthorize(feed, client_id, client_secret, api_key, code)
        client = EnphaseClient(client_id, client_secret, api_key, tokens, self._limiter)
        system_id = self._resolve_system(client, self._system_id(data))
        self._probe(client, system_id)
        self._database.execute(
            """
            UPDATE enphase_feeds
            SET client_id_sealed = %s, client_secret_sealed = %s, api_key_sealed = %s,
                system_id_sealed = %s, system_id_hash = %s, access_token_sealed = %s,
                refresh_token_sealed = %s, token_expires_at = %s, calls_budget = %s,
                active = %s, production_path = %s, last_error = ''
            WHERE id = %s
            """,
            (
                self._database.encrypt(client_id),
                self._database.encrypt(client_secret),
                self._database.encrypt(api_key),
                self._database.encrypt(system_id),
                self._database.blind_index(system_id),
                self._database.encrypt(client.tokens.access_token),
                self._database.encrypt(client.tokens.refresh_token),
                client.tokens.expires_at.isoformat() if client.tokens.expires_at is not None else None,
                self._budget(data),
                bool(data.get("active")),
                client.production_path,
                feed_id,
            ),
        )
        return {"message": "Enphase feed updated."}

    def _reauthorize(
        self,
        feed: dict[str, Any],
        client_id: str,
        client_secret: str,
        api_key: str,
        code: str,
    ) -> EnphaseTokens:
        """A fresh code starts over; without one the stored pair must still work."""
        stored = EnphaseTokens(
            access_token=self._database.decrypt(str(feed["access_token"])),
            refresh_token=self._database.decrypt(str(feed["refresh_token"])),
            expires_at=feed["token_expires_at"],
        )
        if not code:
            return stored
        return EnphaseClient(client_id, client_secret, api_key, None, self._limiter).exchange(code)

    def delete_feed(self, user: SessionUser, feed_id: int) -> dict[str, str]:
        self._require_admin(user)
        self._require_feed(user, feed_id)
        self._database.execute("DELETE FROM enphase_feeds WHERE id = %s", (feed_id,))
        return {"message": "Enphase feed deleted, with everything it had collected."}

    def restart_backfill(self, user: SessionUser, feed_id: int) -> dict[str, str]:
        """Walk both histories again; stored points are kept and refreshed."""
        self._require_admin(user)
        self._require_feed(user, feed_id)
        self._database.execute(
            """
            UPDATE enphase_feeds
            SET backfill_from = NULL, backfill_done = false, fine_from = NULL, fine_done = false, last_sync_at = NULL
            WHERE id = %s
            """,
            (feed_id,),
        )
        return {"message": "History import restarted. It starts within a minute, budget permitting."}

    def series(self, user: SessionUser, house_id: int, days: int, previous: bool, offset: int) -> dict[str, Any]:
        """The house's solar over one `days`-long period, bucketed like the rest.

        Production and consumption are counters and so are summed; the battery
        is a level and so is averaged. Which rows answer is decided by the
        bucket: a day or a week is served by the quarter-hourly telemetry, a
        month or a year by the daily totals, and never by both at once - the
        same hour exists in each resolution and adding them would double it.
        """
        self._require_house(user, house_id)
        bucket_minutes = dict(Constants.enphase_ranges).get(days)
        if bucket_minutes is None:
            choices = ", ".join(str(range_days) for range_days, _ in Constants.enphase_ranges)
            raise AppException(400, f"The range must be one of {choices} days.")
        if offset < 0:
            raise AppException(400, "The offset counts periods back from now.")
        # One reading of the clock for the whole answer: the window's end and the
        # wait named beside it must not drift apart by the length of a query.
        now = datetime.now(UTC)
        until = now - timedelta(days=days * offset)
        since = until - timedelta(days=days * (2 if previous else 1))
        daily = bucket_minutes >= Constants.enphase_daily_bucket_minutes
        window = (
            timedelta(minutes=bucket_minutes),
            house_id,
            Constants.enphase_daily_bucket_minutes,
            since.isoformat(),
            until.isoformat(),
        )
        rows = self._database.fetch_all(self._series_query(daily), (*window, Constants.enphase_source_local, *window, Constants.enphase_source_cloud))
        points = [self._point(row) for row in rows]
        latest = self._latest(house_id)
        live = self._live(house_id)
        return {
            "days": days,
            "bucket_minutes": bucket_minutes,
            "previous": previous,
            "offset": offset,
            "until": until.isoformat(),
            "unit": "kWh",
            "daily": daily,
            "points": points,
            "latest": latest,
            "live": live,
            "stamp": SeriesPulse.stamp(points, latest, live),
            "next_poll_seconds": SeriesPulse.next_poll(self._due(house_id), now),
        }

    def _due(self, house_id: int) -> list[datetime | None]:
        """When either feed behind the solar graph could next have something new.

        Two sources on two entirely different clocks. The gateway is pushed by
        Home Assistant at whatever cadence the house set, which is measured
        from the gap between two pushes rather than assumed. The cloud is
        pulled at a pace derived from what is left of the month's allowance,
        which only ever grows: the floor of that pace is used here, so the page
        may look a little early but never sleeps past the answer.

        A house with only one of the two answers for one of them, and the
        caller takes whichever comes first.
        """
        gateway = self._database.fetch_one(
            "SELECT updated_at, push_seconds FROM enphase_live WHERE house_id = %s",
            (house_id,),
        )
        cloud = self._database.fetch_one(
            """
            SELECT MIN(COALESCE(last_sync_at + %s, now())) AS due
            FROM enphase_feeds WHERE house_id = %s AND active AND source = %s
            """,
            (
                timedelta(seconds=Constants.enphase_sync_min_seconds + Constants.enphase_tick_seconds),
                house_id,
                Constants.enphase_source_cloud,
            ),
        )
        pushed: datetime | None = None
        if gateway is not None:
            landed: datetime = gateway["updated_at"]
            cadence = gateway["push_seconds"] or Constants.realtime_push_default_seconds
            pushed = landed + timedelta(seconds=int(cadence))
        synced: datetime | None = None if cloud is None else cloud["due"]
        return [pushed, synced]

    @classmethod
    def _series_query(cls, daily: bool) -> str:
        """Both sources bucketed apart, then the live one laid over the cloud's.

        The two feeds describe the same panels, so adding them would double
        every reading a house collects both ways. Preferring one whole source
        over the other would be wrong too: Home Assistant only knows what it has
        been up for, and the cloud is what covers the hours it was not. So the
        choice is made a bucket at a time - live where there is live, cloud
        underneath - which is also why they must be grouped before they meet.
        """
        side = f"""
            SELECT date_bin(%s, enphase_points.measured_at, TIMESTAMPTZ '2000-01-01') AS bucket,
                   SUM(enphase_points.production) AS production,
                   SUM(enphase_points.consumption) AS consumption,
                   AVG(enphase_points.battery_level) AS battery_level
            FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
              AND enphase_points.span_minutes {"=" if daily else "<"} %s
              AND enphase_points.measured_at >= %s AND enphase_points.measured_at < %s
              AND enphase_feeds.source = %s
            GROUP BY bucket
            """
        return f"""
            WITH live AS ({side}), cloud AS ({side})
            SELECT COALESCE(live.bucket, cloud.bucket) AS bucket,
                   COALESCE(live.production, cloud.production) AS production,
                   COALESCE(live.consumption, cloud.consumption) AS consumption,
                   COALESCE(live.battery_level, cloud.battery_level) AS battery_level
            FROM live FULL OUTER JOIN cloud ON cloud.bucket = live.bucket
            ORDER BY bucket
            """

    @classmethod
    def _point(cls, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "at": row["bucket"].isoformat(),
            "production": cls._rounded(row["production"], 4),
            "consumption": cls._rounded(row["consumption"], 4),
            "battery_level": cls._rounded(row["battery_level"], 1),
        }

    def _local(self, house_id: int) -> dict[str, Any]:
        """What the Home Assistant feed has collected, if the house has one."""
        row = self._database.fetch_one(
            """
            SELECT enphase_feeds.id, COUNT(enphase_points.id) AS points,
                   MIN(enphase_points.measured_at) AS first_at, MAX(enphase_points.measured_at) AS last_at
            FROM enphase_feeds LEFT JOIN enphase_points ON enphase_points.feed_id = enphase_feeds.id
            WHERE enphase_feeds.house_id = %s AND enphase_feeds.source = %s
            GROUP BY enphase_feeds.id
            """,
            (house_id, Constants.enphase_source_local),
        )
        if row is None:
            return {"id": 0, "points": 0, "first_point_at": "", "last_point_at": ""}
        return {
            "id": int(row["id"]),
            "points": int(row["points"]),
            "first_point_at": self._moment(row["first_at"]),
            "last_point_at": self._moment(row["last_at"]),
        }

    def _live(self, house_id: int) -> dict[str, Any]:
        """What Home Assistant last saw the gateway doing, in watts.

        A house on the cloud feed alone has none of this, and says so with an
        empty instant rather than a zero - nothing at all is a different fact
        from panels making nothing.
        """
        row = self._database.fetch_one(
            """
            SELECT measured_at, production_power, consumption_power, battery_level
            FROM enphase_live WHERE house_id = %s
            """,
            (house_id,),
        )
        if row is None:
            return {"at": "", "production_power": None, "consumption_power": None, "battery_level": None}
        return {
            "at": self._moment(row["measured_at"]),
            "production_power": self._rounded(row["production_power"], 1),
            "consumption_power": self._rounded(row["consumption_power"], 1),
            "battery_level": self._rounded(row["battery_level"], 1),
        }

    def _latest(self, house_id: int) -> dict[str, Any]:
        """The freshest quarter-hour, which is what the tiles show.

        Production, consumption and the battery are three separate calls and a
        system without batteries never answers the third, so the newest row that
        carries each one is found on its own: one stream being quiet must not
        blank the other two.
        """
        result: dict[str, Any] = {"at": "", "production": None, "consumption": None, "battery_level": None}
        for field in ("production", "consumption", "battery_level"):
            row = self._database.fetch_one(
                f"""
                SELECT enphase_points.measured_at, enphase_points.{field} AS value
                FROM enphase_points JOIN enphase_feeds ON enphase_feeds.id = enphase_points.feed_id
                WHERE enphase_feeds.house_id = %s AND enphase_feeds.active
                  AND enphase_points.span_minutes < %s AND enphase_points.{field} IS NOT NULL
                ORDER BY enphase_points.measured_at DESC LIMIT 1
                """,
                (house_id, Constants.enphase_daily_bucket_minutes),
            )
            if row is None:
                continue
            result[field] = self._rounded(row["value"], 4 if field != "battery_level" else 1)
            result["at"] = max(result["at"], self._moment(row["measured_at"]))
        return result

    def _resolve_system(self, client: EnphaseClient, wanted: str) -> str:
        """The system to collect, checked against the ones the account actually has."""
        systems = client.systems()
        if not systems:
            raise AppException(502, "That Enphase account has no system on it.")
        known = [system.system_id for system in systems]
        if not wanted:
            if len(known) > 1:
                raise AppException(400, f"This account has several systems. Enter one of these ids: {', '.join(known)}.")
            return known[0]
        if wanted not in known:
            raise AppException(400, self._wrong_system(systems))
        return wanted

    @classmethod
    def _wrong_system(cls, systems: list[EnphaseSystem]) -> str:
        named = ", ".join(f"{system.system_id} ({system.name})" if system.name else system.system_id for system in systems)
        return f"This account has no system with that id. It has: {named}."

    @classmethod
    def _probe(cls, client: EnphaseClient, system_id: str) -> None:
        """One day of telemetry, thrown away: it is the credentials being tested."""
        client.production(system_id, datetime.now(UTC).date())

    @classmethod
    def _budget(cls, data: dict[str, Any]) -> int:
        result = int(data.get("calls_budget") or 0) or Constants.enphase_calls_budget
        if result < 1:
            raise AppException(400, "The monthly call budget must be a positive number.")
        return result

    @classmethod
    def _system_id(cls, data: dict[str, Any]) -> str:
        """Empty is allowed: the account is asked, and one system needs no choosing."""
        result = str(data.get("system_id") or "").strip()
        if result and not re.fullmatch(r"[0-9]{1,20}", result):
            raise AppException(400, "An Enphase system id is digits only.")
        return result

    @classmethod
    def _rounded(cls, value: Any, digits: int) -> float | None:
        return None if value is None else round(float(value), digits)

    @classmethod
    def _moment(cls, value: datetime | None) -> str:
        return value.isoformat() if value is not None else ""

    def _visible_house_ids(self, user: SessionUser) -> list[int]:
        rows = self._database.fetch_all("SELECT house_id FROM user_houses WHERE user_id = %s ORDER BY house_id", (user.user_id,))
        return [int(row["house_id"]) for row in rows]

    @classmethod
    def _require_admin(cls, user: SessionUser) -> None:
        if not user.is_admin:
            raise AppException(403, "Only admins can do this.")

    def _require_house(self, user: SessionUser, house_id: int) -> None:
        row = self._database.fetch_one("SELECT id FROM houses WHERE id = %s", (house_id,))
        if row is None:
            raise AppException(404, "The house was not found.")
        if house_id not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")

    def _require_feed(self, user: SessionUser, feed_id: int) -> dict[str, Any]:
        result = self._database.fetch_one(
            """
            SELECT id, house_id, client_secret_sealed AS client_secret, api_key_sealed AS api_key,
                   access_token_sealed AS access_token, refresh_token_sealed AS refresh_token, token_expires_at
            FROM enphase_feeds WHERE id = %s AND source = %s
            """,
            (feed_id, Constants.enphase_source_cloud),
        )
        if result is None:
            raise AppException(404, "The Enphase feed was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result
