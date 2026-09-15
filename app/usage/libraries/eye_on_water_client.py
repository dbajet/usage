from __future__ import annotations

import csv
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, tzinfo
from http.cookiejar import CookieJar
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage.constants.constants import Constants
from usage.structures.app_exception import AppException
from usage.structures.water_meter import WaterMeter
from usage.structures.water_point import WaterPoint


class EyeOnWaterClient:
    """Drives EyeOnWater's "Export Data" button, and nothing else.

    The portal has no documented API, so the client sticks to the four calls
    the button itself makes: sign in, ask for a CSV over a date range, poll
    the task until it is ready, download it. No internal JSON endpoint, no
    meter discovery - the meter uuid is configuration, read once off the
    export URL in the browser.

    The CSV reports `Read` in the meter's own unit whatever unit the export
    asks for (a meter counting in CCF answers in CCF even for a request in
    cubic metres), so both columns are converted from the unit the CSV names
    rather than the one we asked for. Everything is stored in cubic metres.
    """

    def __init__(self, hostname: str, username: str, password: str, export_unit: str = "") -> None:
        self._hostname = hostname or Constants.water_host_default
        self._username = username
        self._password = password
        self._export_unit = export_unit or Constants.water_export_unit
        self._opener_built: urllib.request.OpenerDirector | None = None
        self._signed_in = False

    def export(self, meter_uuid: str, start: date, end: date) -> list[WaterPoint]:
        """The consumption of one meter between two days, both ends included."""
        self._sign_in()
        task_id = self._initiate(meter_uuid, start, end)
        return self._points(self._download(self._await_export(task_id)))

    def meters(self) -> list[WaterMeter]:
        """Every meter this account can see, as the portal's own picker lists them.

        The one call outside the export flow, and it runs once, when a feed is
        set up. It earns its place: the export answers a wrong meter uuid with
        "list index out of range" from inside their own task, so the number is
        far better asked for than copied.
        """
        self._sign_in()
        payload = self._json(self._post(self._absolute(Constants.water_search_path), {"query": {"match_all": {}}}))
        wrapper = payload.get("elastic_results") or {}
        hits = (wrapper.get("hits") or {}).get("hits") or [] if isinstance(wrapper, dict) else []
        result: list[WaterMeter] = []
        for hit in hits if isinstance(hits, list) else []:
            source = hit.get("_source") or {} if isinstance(hit, dict) else {}
            meter = source.get("meter") or {} if isinstance(source, dict) else {}
            uuid = str(meter.get("meter_uuid") or "") if isinstance(meter, dict) else ""
            if not uuid:
                continue
            result.append(
                WaterMeter(
                    uuid=uuid,
                    meter_id=str(meter.get("meter_id") or ""),
                    timezone=str(meter.get("timezone") or ""),
                ),
            )
        return result

    def _opener(self) -> urllib.request.OpenerDirector:
        # The session lives in the cookie jar: the sign-in sets it on a redirect,
        # so the response itself carries no Set-Cookie at all.
        if self._opener_built is None:
            self._opener_built = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        return self._opener_built

    def _sign_in(self) -> None:
        if self._signed_in:
            return
        payload = urllib.parse.urlencode({"username": self._username, "password": self._password}).encode("utf-8")
        try:
            with self._opener().open(self._absolute(Constants.water_sign_in_path), payload, timeout=Constants.water_timeout_seconds) as response:
                response.read()
        except urllib.error.HTTPError as error:
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "EyeOnWater could not be reached.") from None
        # A 200 here proves nothing: the sign-in answers with the login page when
        # the credentials are refused. The first export call is what tells us.
        self._signed_in = True

    def _initiate(self, meter_uuid: str, start: date, end: date) -> str:
        query = urllib.parse.urlencode(
            {
                "export_unit": self._export_unit,
                "site": "residential",
                "export_resolution": Constants.water_resolution,
                "start-date": start.strftime("%m/%d/%Y"),
                "end-date": end.strftime("%m/%d/%Y"),
                "meter_uuid": meter_uuid,
                "row-format": "range",
                "export_all": "false",
                "_": self._stamp(),
            },
        )
        status = self._json(self._fetch(f"{self._absolute(Constants.water_initiate_path)}?{query}"))
        result = str(status.get("task_id") or "")
        if not result:
            raise AppException(401, "EyeOnWater did not start the export; the username or password was probably refused.")
        return result

    def _await_export(self, task_id: str) -> str:
        path = f"{Constants.water_status_path}{urllib.parse.quote(task_id, safe=':')}"
        for attempt in range(Constants.water_poll_attempts):
            if attempt:
                time.sleep(Constants.water_poll_seconds)
            status = self._json(self._fetch(f"{self._absolute(path)}?_={self._stamp()}"))
            state = str(status.get("state") or "")
            if state == "done":
                return self._result_url(status)
            if state == "error":
                raise AppException(502, str(status.get("message") or "EyeOnWater could not build the export."))
        raise AppException(504, "EyeOnWater did not finish the export in time.")

    def _result_url(self, status: dict[str, Any]) -> str:
        """The download link, wherever this version of the portal keeps it.

        Naming one key was a guess, and a wrong one: the payload is searched for
        the first string that looks like a link instead. When there is none, the
        message carries the shape of what came back - the keys, never the values,
        since one of them is the signed URL - so the next shape can be read off
        the error rather than out of a log nobody is watching.
        """
        found = self._first_link(status.get("result", status))
        if not found:
            raise AppException(502, self._refusal(status))
        return self._absolute(found)

    @classmethod
    def _refusal(cls, status: dict[str, Any]) -> str:
        """What the portal said, when it finished the task without a file.

        A done task whose result carries a message instead of a link is
        EyeOnWater explaining itself - most often that the meter uuid matched
        nothing. Its own words are worth far more than ours, so they are passed
        straight through; the shape of the payload is only the last resort.
        """
        result = status.get("result")
        if isinstance(result, str):
            result = cls._json(result) or result
        message = str((result.get("message") if isinstance(result, dict) else "") or "").strip()
        if not message:
            message = str(status.get("message") or "").strip()
        if not message:
            return f"EyeOnWater finished the export without saying where it is; it sent {cls._shape(status)}."
        return f"EyeOnWater did not produce an export: {message[:Constants.water_message_max]}"

    @classmethod
    def _first_link(cls, value: Any) -> str:
        if isinstance(value, str):
            text = value.strip()
            # A JSON document handed over as a string: look inside it first, or the
            # whole document reads as a link the moment it mentions one.
            if decoded := cls._json(text):
                return cls._first_link(decoded)
            if text.startswith(("/", "http://", "https://")) or ("export" in text and "/" in text):
                return text
            return ""
        if isinstance(value, dict):
            for item in value.values():
                if found := cls._first_link(item):
                    return found
        if isinstance(value, list):
            for item in value:
                if found := cls._first_link(item):
                    return found
        return ""

    @classmethod
    def _shape(cls, value: Any, depth: int = 0) -> str:
        """The keys of a payload, two levels deep, and none of its values."""
        if isinstance(value, str):
            decoded = cls._json(value)
            return cls._shape(decoded, depth) if decoded else ""
        if isinstance(value, list):
            return "[...]" if value else "[]"
        if not isinstance(value, dict):
            return ""
        if not value:
            return "{}"
        if depth >= 2:
            return "{...}"
        return "{" + ", ".join(f"{key}{cls._shape(item, depth + 1)}" for key, item in sorted(value.items())) + "}"

    def _download(self, url: str) -> str:
        return self._fetch(url)

    def _post(self, url: str, payload: dict[str, Any]) -> str:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with self._opener().open(request, None, timeout=Constants.water_timeout_seconds) as response:
                return str(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "EyeOnWater could not be reached.") from None

    def _fetch(self, url: str) -> str:
        try:
            with self._opener().open(url, None, timeout=Constants.water_timeout_seconds) as response:
                return str(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "EyeOnWater could not be reached.") from None

    def _points(self, text: str) -> list[WaterPoint]:
        result: list[WaterPoint] = []
        previous: datetime | None = None
        seen = 0
        for row in csv.DictReader(io.StringIO(text)):
            if self._is_blank(row):
                continue
            seen += 1
            moment = self._moment(str(row.get("Read_Time") or ""), self._zone(str(row.get("Timezone") or "")), previous)
            volume = self._cubic_meters(self._number(row.get("Flow")), str(row.get("Flow_Unit") or ""))
            if moment is None or volume is None:
                continue
            previous = moment
            result.append(
                WaterPoint(
                    measured_at=moment,
                    volume=round(volume, 6),
                    reading=self._cubic_meters(self._number(row.get("Read")), str(row.get("Read_Unit") or "")),
                    method=str(row.get("Read_Method") or "").strip(),
                ),
            )
        # Rows that all fail to parse mean the export changed shape under us. This
        # will not fix itself on the next tick, so it is 422 rather than 502: the
        # backfill takes that to mean "move on" instead of retrying for ever.
        if seen and not result:
            raise AppException(422, "The EyeOnWater export was not in the expected format.")
        result.sort(key=lambda point: point.measured_at)
        return result

    @classmethod
    def _is_blank(cls, row: dict[str, str | None]) -> bool:
        """The portal's way of saying "nothing for this range".

        It is not an empty file: the CSV carries its header and one row with the
        account and the meter filled in and every reading column empty. Counting
        that as a row would make an ordinary barren month look like a format
        change, which is the one thing the count exists to catch.
        """
        return not any(str(row.get(field) or "").strip() for field in ("Read_Time", "Read", "Flow"))

    @classmethod
    def _zone(cls, name: str) -> tzinfo:
        """The time zone the export is written in, or no export at all.

        The CSV names it in IANA terms and sometimes by a legacy alias -
        "US/Pacific" rather than "America/Los_Angeles" - and a slim image ships
        a tz database with the aliases left out. Falling back to UTC there was a
        silent way to file every reading hours from where it belongs, which is
        worse than filing none: an unknown zone now stops the export and says so.
        """
        text = name.strip()
        if not text:
            return UTC
        try:
            return ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            raise AppException(502, f"This server does not know the time zone {text} that the export is written in.") from None

    @classmethod
    def _moment(cls, raw: str, zone: tzinfo, previous: datetime | None) -> datetime | None:
        text = raw.strip()
        if not text:
            return None
        try:
            naive = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                naive = datetime.fromisoformat(text)
            except ValueError:
                return None
        result = naive.replace(tzinfo=zone).astimezone(UTC)
        # The CSV gives local time with no offset, so on the autumn fall-back the
        # hour repeats and its second pass would land on the first one's instant.
        # The rows arrive in order: a moment that does not move forward is that
        # second pass, and only then is the repeated hour's later side meant.
        if previous is not None and result <= previous:
            shifted = naive.replace(tzinfo=zone, fold=1).astimezone(UTC)
            if shifted > previous:
                result = shifted
        return result

    @classmethod
    def _cubic_meters(cls, value: float | None, unit: str) -> float | None:
        if value is None:
            return None
        factor = dict(Constants.water_cubic_meters).get(unit.strip().upper())
        if factor is None:
            return None
        return round(value * factor, 6)

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        text = str(raw if raw is not None else "").strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _json(cls, raw: str) -> dict[str, Any]:
        try:
            result = json.loads(raw)
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}

    @classmethod
    def _stamp(cls) -> int:
        return int(time.time() * 1000)

    @classmethod
    def _http_failure(cls, error: urllib.error.HTTPError) -> AppException:
        if error.code == 400:
            return AppException(401, "EyeOnWater rejected the username or password.")
        if error.code == 403:
            return AppException(429, "EyeOnWater is refusing more requests for now.")
        return AppException(502, "EyeOnWater could not be reached.")

    def _absolute(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return f"https://{self._hostname}/{url.lstrip('/')}"
