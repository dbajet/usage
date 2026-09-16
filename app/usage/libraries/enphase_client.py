from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.rate_limiter import RateLimiter
from usage.structures.app_exception import AppException
from usage.structures.enphase_point import EnphasePoint
from usage.structures.enphase_system import EnphaseSystem
from usage.structures.enphase_tokens import EnphaseTokens


class EnphaseClient:
    """The Enphase Enlighten developer API, version 4.

    Two credentials guard every call and they are not interchangeable: the API
    key says which plan the request is billed to, and the bearer token says
    which homeowner's account it may read. A request carrying one and not the
    other is refused, which is worth knowing because the refusals look nothing
    alike - a missing key is a 401 about the key, a stale token is a 401 about
    the token, and only the second one is worth retrying.

    So a 401 is answered exactly once, by refreshing and trying again. Enphase
    rotates the refresh token every time it is used, so whoever owns this client
    must persist `tokens` after any call that may have refreshed - the pair in
    the database is the only copy, and the previous one is already dead.

    Every call is counted. The plan's allowance is monthly and small on the free
    tier, so the sync needs to know what a tick actually cost rather than
    guessing from the number of endpoints it meant to touch.

    That allowance has a per-minute ceiling under it, and the two need entirely
    different defences. Pacing the ticks protects the monthly budget and does
    nothing at all for the ceiling, because a backfill tick asks for a dozen
    calls inside one second. So every request - the metered ones and the OAuth
    ones alike - goes through the shared `limiter` first, which holds the burst
    back rather than letting Enphase refuse it.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_key: str,
        tokens: EnphaseTokens | None = None,
        limiter: RateLimiter | None = None,
        production_path: str = "",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_key = api_key
        self._tokens = tokens or EnphaseTokens(access_token="", refresh_token="")
        self._limiter = limiter
        self._production_path = production_path
        self._calls = 0

    @property
    def tokens(self) -> EnphaseTokens:
        """The current pair, which a refresh may have replaced since it was given."""
        return self._tokens

    @property
    def production_path(self) -> str:
        """Which endpoint answers for production here, once anything has."""
        return self._production_path

    @property
    def calls(self) -> int:
        """API requests made by this client, for the plan's monthly allowance."""
        return self._calls

    @classmethod
    def authorize_url(cls, client_id: str) -> str:
        """Where a person sends their browser, once, to authorise this application."""
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": Constants.enphase_redirect_uri,
            },
        )
        return f"https://{Constants.enphase_host}{Constants.enphase_authorize_path}?{query}"

    def exchange(self, code: str) -> EnphaseTokens:
        """Turn the pasted authorisation code into the first pair of tokens."""
        return self._store(
            self._token_call(
                {
                    "grant_type": "authorization_code",
                    "redirect_uri": Constants.enphase_redirect_uri,
                    "code": code,
                },
                "Enphase refused that authorisation code. They expire within minutes, so it may simply be stale.",
            ),
        )

    def refresh(self) -> EnphaseTokens:
        if not self._tokens.refresh_token:
            raise AppException(401, "This Enphase feed has never been authorised.")
        return self._store(
            self._token_call(
                {"grant_type": "refresh_token", "refresh_token": self._tokens.refresh_token},
                "Enphase refused the stored authorisation. A refresh token lasts about a month, "
                "so a feed left paused for longer has to be authorised again.",
            ),
        )

    def systems(self) -> list[EnphaseSystem]:
        """Every system this account can see, as the picker in Enlighten lists them."""
        payload = self._get(Constants.enphase_systems_path, {"size": Constants.enphase_page_size})
        result: list[EnphaseSystem] = []
        for entry in payload.get("systems") or []:
            if not isinstance(entry, dict):
                continue
            system_id = str(entry.get("system_id") or entry.get("id") or "")
            if not system_id:
                continue
            result.append(
                EnphaseSystem(
                    system_id=system_id,
                    name=str(entry.get("name") or ""),
                    status=str(entry.get("status") or ""),
                ),
            )
        return result

    def production(self, system_id: str, day: date) -> list[EnphasePoint]:
        """What the panels made, from the meter if there is one and the inverters if not.

        Production CTs are usual but not universal, and a system without them is
        not refused by the meter endpoint - it is answered with an empty day,
        which looks exactly like night. That was the whole bug: a fallback that
        waited for a refusal never fired, and such a system collected
        consumption and no production at all.

        So an empty answer falls through too, and the endpoint that finally says
        something is remembered. Only the learning costs the extra call: once
        the path is known nothing is tried twice, and a system that really is
        idle at 3am is not re-asked every tick for ever.
        """
        if self._production_path:
            return self._telemetry(self._path_of(self._production_path), system_id, day, "production")
        return self._discover_production(system_id, day)

    def _discover_production(self, system_id: str, day: date) -> list[EnphasePoint]:
        """Ask each endpoint in turn, and keep the name of whichever answers."""
        for name in (Constants.enphase_production_meter, Constants.enphase_production_micro):
            try:
                result = self._telemetry(self._path_of(name), system_id, day, "production")
            except AppException as exception:
                if exception.status_code != Constants.enphase_unreadable_status:
                    raise
                continue
            if result:
                self._production_path = name
                return result
        # Both quiet: a night, most likely. Nothing is learned from that, so the
        # question stays open for a day with some daylight in it.
        return []

    @classmethod
    def _path_of(cls, name: str) -> str:
        if name == Constants.enphase_production_micro:
            return Constants.enphase_production_micro_path
        return Constants.enphase_production_path

    def consumption(self, system_id: str, day: date) -> list[EnphasePoint]:
        return self._telemetry(Constants.enphase_consumption_path, system_id, day, "consumption")

    def battery(self, system_id: str, day: date) -> list[EnphasePoint]:
        return self._telemetry(Constants.enphase_battery_path, system_id, day, "battery")

    def daily(self, system_id: str, start: date | None, end: date | None) -> list[EnphasePoint]:
        """Daily totals for a whole stretch of history, in two calls.

        This is the only affordable way to own years of data: the lifetime
        endpoints answer a multi-year range in one request each, where walking
        the same years through the quarter-hourly telemetry would be three
        calls per day and several times the monthly allowance for one month
        of history.
        """
        produced = self._lifetime(Constants.enphase_energy_lifetime_path, system_id, start, end, "production")
        consumed = self._lifetime(Constants.enphase_consumption_lifetime_path, system_id, start, end, "consumption")
        merged: dict[datetime, EnphasePoint] = {}
        for point in [*produced, *consumed]:
            known = merged.get(point.measured_at)
            merged[point.measured_at] = point if known is None else known._replace(
                production=known.production if point.production is None else point.production,
                consumption=known.consumption if point.consumption is None else point.consumption,
            )
        return sorted(merged.values(), key=lambda point: point.measured_at)

    def _lifetime(
        self,
        path: str,
        system_id: str,
        start: date | None,
        end: date | None,
        field: str,
    ) -> list[EnphasePoint]:
        """One day per element of a flat list, counted forward from `start_date`.

        The list is the answer's whole payload - there are no timestamps in it -
        so the day of an element is its index, and a list that starts on a date
        other than the one asked for has to be read from the date it names.

        Asking with no start at all is the point of the endpoint: it answers with
        the system's whole life, which is how years of daily totals cost one call
        rather than one call per day.
        """
        params: dict[str, Any] = {}
        if start is not None:
            params["start_date"] = start.isoformat()
        if end is not None:
            params["end_date"] = end.isoformat()
        payload = self._get(path.format(system_id=urllib.parse.quote(system_id)), params)
        values = payload.get(field)
        if not isinstance(values, list):
            return []
        first = self._day(str(payload.get("start_date") or "")) or start
        if first is None:
            # Without a start date the indexes mean nothing: better no rows
            # than a year of production filed from today backwards.
            return []
        result: list[EnphasePoint] = []
        for index, value in enumerate(values):
            watt_hours = self._number(value)
            if watt_hours is None:
                continue
            moment = datetime.combine(first + timedelta(days=index), datetime.min.time(), tzinfo=UTC)
            result.append(
                EnphasePoint(
                    measured_at=moment,
                    span_minutes=Constants.enphase_daily_bucket_minutes,
                    production=self._kwh(watt_hours) if field == "production" else None,
                    consumption=self._kwh(watt_hours) if field == "consumption" else None,
                ),
            )
        return result

    def _telemetry(self, path: str, system_id: str, day: date, field: str) -> list[EnphasePoint]:
        """One day of intervals from one of the three streams.

        `start_at` is an instant, not a date, and the answer runs from it for a
        day. Midnight UTC is used deliberately: everything in this app is stored
        in UTC and bucketed there, so a day that starts at the system's local
        midnight would file the same interval under two different labels
        depending on which endpoint returned it.
        """
        start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        payload = self._get(
            path.format(system_id=urllib.parse.quote(system_id)),
            {"start_at": int(start.timestamp()), "granularity": Constants.enphase_granularity},
        )
        intervals = payload.get("intervals")
        if not isinstance(intervals, list):
            return []
        span = self._span(intervals)
        result: list[EnphasePoint] = []
        for interval in intervals:
            if not isinstance(interval, dict):
                continue
            end_at = self._number(interval.get("end_at"))
            if end_at is None:
                continue
            # An interval is labelled by when it started: a bar covering 10:00
            # to 10:15 belongs at 10:00, and Enphase reports the far end.
            moment = datetime.fromtimestamp(end_at, UTC) - timedelta(minutes=span)
            point = self._value(interval, field, moment, span)
            if point is not None:
                result.append(point)
        result.sort(key=lambda point: point.measured_at)
        return result

    @classmethod
    def _value(cls, interval: dict[str, Any], field: str, moment: datetime, span: int) -> EnphasePoint | None:
        if field == "battery":
            level = cls._percent(interval)
            if level is None:
                return None
            return EnphasePoint(measured_at=moment, span_minutes=span, battery_level=level)
        energy = cls._kwh(cls._number(interval.get("enwh")))
        if energy is None:
            return None
        return EnphasePoint(
            measured_at=moment,
            span_minutes=span,
            production=energy if field == "production" else None,
            consumption=energy if field == "consumption" else None,
        )

    @classmethod
    def _percent(cls, interval: dict[str, Any]) -> float | None:
        """The state of charge, wherever this account's battery reports it.

        Enphase has written the charge both as a bare number and as an object
        with a `percent` inside it, and a system with no battery leaves it out
        altogether. Naming one shape would make a working battery look like an
        absent one, so every shape that carries a number is accepted and
        anything else is simply no reading.
        """
        for key in ("soc", "percent", "soc_percent", "state_of_charge"):
            raw = interval.get(key)
            if isinstance(raw, dict):
                raw = raw.get("percent", raw.get("value"))
            number = cls._number(raw)
            if number is not None:
                return round(max(0.0, min(Constants.enphase_battery_max_percent, number)), 2)
        return None

    @classmethod
    def _span(cls, intervals: list[Any]) -> int:
        """How long one interval is, read off the data rather than assumed.

        Enphase serves five-minute microinverter telemetry and quarter-hourly
        meter telemetry through the same shape, and `granularity` names the
        range asked for rather than the resolution answered. The gap between
        two consecutive ends is the only honest source.
        """
        ends = [cls._number(entry.get("end_at")) for entry in intervals if isinstance(entry, dict)]
        stamps = sorted(stamp for stamp in ends if stamp is not None)
        gaps = sorted({int(round((later - earlier) / 60)) for earlier, later in zip(stamps, stamps[1:])})
        positive = [gap for gap in gaps if gap > 0]
        if not positive:
            return Constants.enphase_default_span_minutes
        return positive[0]

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """One authenticated call, with a single retry after refreshing the token."""
        if self._stale():
            self.refresh()
        try:
            return self._json_or_fail(self._fetch(self._url(path, params)))
        except AppException as exception:
            if exception.status_code != 401:
                raise
            # The one retry: the access token died earlier than its stated life,
            # which happens when the homeowner re-authorises somewhere else.
            self.refresh()
            return self._json_or_fail(self._fetch(self._url(path, params)))

    def _stale(self) -> bool:
        if not self._tokens.access_token:
            return True
        if self._tokens.expires_at is None:
            return False
        return datetime.now(UTC) >= self._tokens.expires_at - timedelta(seconds=Constants.enphase_token_skew_seconds)

    def _url(self, path: str, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode({**params, "key": self._api_key})
        return f"https://{Constants.enphase_host}{path}?{query}"

    def _fetch(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._tokens.access_token}", "Accept": "application/json"},
        )
        self._await_slot()
        self._calls += 1
        try:
            with urllib.request.urlopen(request, timeout=Constants.enphase_timeout_seconds) as response:
                return str(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "Enphase could not be reached.") from None

    def _token_call(self, params: dict[str, str], refusal: str) -> dict[str, Any]:
        """The OAuth endpoint, which authenticates the application, not the user.

        The application's own id and secret go in an HTTP Basic header and the
        grant goes in the query string: Enphase does not read a form body here.
        """
        secret = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        url = f"https://{Constants.enphase_host}{Constants.enphase_token_path}?{urllib.parse.urlencode(params)}"
        # Not billed to the monthly allowance, but it is still a request to the
        # same host on the same key, and a refresh lands in the middle of a burst.
        self._await_slot()
        request = urllib.request.Request(
            url,
            data=b"",
            headers={"Authorization": f"Basic {secret}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=Constants.enphase_timeout_seconds) as response:
                payload = self._json(str(response.read().decode("utf-8", "replace")))
        except urllib.error.HTTPError as error:
            if error.code in (400, 401):
                raise AppException(401, refusal) from None
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "Enphase could not be reached.") from None
        if not str(payload.get("access_token") or ""):
            raise AppException(401, refusal)
        return payload

    def _await_slot(self) -> None:
        """Wait for room under the per-minute ceiling, or say why there is none."""
        if self._limiter is None:
            return
        if not self._limiter.acquire(self._api_key, Constants.enphase_rate_wait_seconds):
            raise AppException(429, "Enphase is being asked as fast as the plan allows; try again in a minute.")

    def _store(self, payload: dict[str, Any]) -> EnphaseTokens:
        """Keep the new pair, including a refresh token that has just rotated."""
        lifetime = self._number(payload.get("expires_in"))
        self._tokens = EnphaseTokens(
            access_token=str(payload.get("access_token") or ""),
            # Enphase always sends the replacement, but a pair with an empty
            # refresh half would be a feed that dies at the next tick: keeping
            # the old one is wrong far less often than storing nothing.
            refresh_token=str(payload.get("refresh_token") or "") or self._tokens.refresh_token,
            expires_at=None if lifetime is None else datetime.now(UTC) + timedelta(seconds=int(lifetime)),
        )
        return self._tokens

    @classmethod
    def _json_or_fail(cls, raw: str) -> dict[str, Any]:
        result = cls._json(raw)
        if not result:
            # A 200 that is not an object is Enphase answering with something
            # other than the API - a captive portal, an error page, a redirect.
            raise AppException(Constants.enphase_unreadable_status, "Enphase answered with something that is not JSON.")
        return result

    @classmethod
    def _json(cls, raw: str) -> dict[str, Any]:
        try:
            result = json.loads(raw)
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}

    @classmethod
    def _day(cls, raw: str) -> date | None:
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None

    @classmethod
    def _kwh(cls, watt_hours: float | None) -> float | None:
        if watt_hours is None:
            return None
        return round(watt_hours / Constants.enphase_watt_hours_per_kwh, 6)

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _http_failure(cls, error: urllib.error.HTTPError) -> AppException:
        if error.code in (401, 403):
            return AppException(401, cls._refusal(error))
        if error.code == 429:
            return AppException(429, "Enphase is refusing more requests: the plan's rate limit is spent.")
        if error.code == 422:
            return AppException(Constants.enphase_unreadable_status, cls._refusal(error))
        return AppException(502, "Enphase could not be reached.")

    @classmethod
    def _refusal(cls, error: urllib.error.HTTPError) -> str:
        """Enphase's own words, which name the credential that is wrong.

        The API key and the bearer token fail with the same status and entirely
        different remedies, and their message says which - passing it through
        saves reading it out of a log nobody is watching.
        """
        try:
            payload = cls._json(str(error.read().decode("utf-8", "replace")))
        except (OSError, ValueError):
            payload = {}
        message = str(payload.get("message") or payload.get("error_description") or payload.get("error") or "").strip()
        if not message:
            return "Enphase refused the request; check the API key and the authorisation."
        return f"Enphase refused the request: {message[:Constants.enphase_message_max]}"
