from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.rate_limiter import RateLimiter
from usage.structures.app_exception import AppException
from usage.structures.switch_bot_device import SwitchBotDevice
from usage.structures.switch_bot_reading import SwitchBotReading


class SwitchBotClient:
    """SwitchBot's cloud API, version 1.1: what the account has, and what a device reads now.

    Every request is signed with the account's token and secret - an HMAC over
    the token, a millisecond timestamp and a nonce - so nothing here is a
    session and there is no login to keep alive.

    Two facts about it shape everything built on top. There is **no history
    endpoint**: the cloud answers "it is 19.4" and never "it became 19.4 at
    14:02", so a house fed this way starts collecting the day it is switched on
    and no backfill is possible at all. And **a refusal usually arrives as a
    200**: SwitchBot puts its own verdict in the body's `statusCode`, where 100
    is success and everything else is a device the hub could not reach, a
    parameter it did not like, or its own internals. Only the credentials fail
    with an HTTP status.
    """

    def __init__(self, token: str, secret: str, limiter: RateLimiter | None = None) -> None:
        self._token = token
        self._secret = secret
        self._limiter = limiter

    def devices(self) -> list[SwitchBotDevice]:
        """Every device on the account, each with the hub that relays it.

        Asked on every tick rather than remembered. It is one call, and it is
        what makes a thermometer paired next year appear on its own: the feed
        follows a hub, and the hub's list is the only thing that changes.
        """
        payload = self._get(Constants.switchbot_devices_path)
        result: list[SwitchBotDevice] = []
        for entry in payload.get("deviceList") or []:
            if not isinstance(entry, dict):
                continue
            device_id = str(entry.get("deviceId") or "")
            if not device_id:
                continue
            result.append(
                SwitchBotDevice(
                    device_id=device_id,
                    name=str(entry.get("deviceName") or ""),
                    device_type=str(entry.get("deviceType") or ""),
                    hub_id=self._hub_id(entry.get("hubDeviceId")),
                ),
            )
        return result

    def status(self, device_id: str) -> SwitchBotReading | None:
        """What one device reads this second, or nothing when it reads no temperature.

        The device type is not consulted: whether something is a thermometer is
        answered by whether it reports a temperature, so a model SwitchBot
        releases next year needs no change here to be collected.
        """
        path = Constants.switchbot_status_path.format(device_id=urllib.parse.quote(device_id))
        payload = self._get(path)
        temperature = self._number(payload.get("temperature"))
        if temperature is None:
            return None
        battery = self._number(payload.get("battery"))
        return SwitchBotReading(
            device_id=device_id,
            temperature=temperature,
            humidity=self._number(payload.get("humidity")),
            battery=None if battery is None else int(round(battery)),
        )

    def setup_webhook(self, url: str) -> None:
        """Ask SwitchBot to post every device's changes to this URL, from now on.

        One URL per account, and every device on it - `deviceList` takes no
        narrower answer. So the events of a house this feed does not follow
        arrive here too, and are dropped on the way in rather than filtered
        here: the account is one thing and the houses behind it are another.
        """
        self._post(
            Constants.switchbot_webhook_setup_path,
            {"action": "setupWebhook", "url": url, "deviceList": Constants.switchbot_webhook_all_devices},
        )

    def delete_webhook(self, url: str) -> None:
        self._post(Constants.switchbot_webhook_delete_path, {"action": "deleteWebhook", "url": url})

    def _get(self, path: str) -> dict[str, Any]:
        """One signed call, unwrapped to the body SwitchBot buried it in."""
        payload = self._json(self._fetch(f"https://{Constants.switchbot_host}{path}"))
        if payload.get("statusCode") != Constants.switchbot_success_code:
            raise AppException(Constants.switchbot_unreadable_status, self._refusal(payload))
        body = payload.get("body")
        return body if isinstance(body, dict) else {}

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """The webhook endpoints, which are the only ones that take a body."""
        payload = self._json(self._fetch(f"https://{Constants.switchbot_host}{path}", json.dumps(body).encode("utf-8")))
        if payload.get("statusCode") != Constants.switchbot_success_code:
            raise AppException(Constants.switchbot_unreadable_status, self._refusal(payload))
        return payload

    def _fetch(self, url: str, body: bytes | None = None) -> str:
        self._await_slot()
        request = urllib.request.Request(url, data=body, headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=Constants.switchbot_timeout_seconds) as response:
                return str(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            raise self._http_failure(error) from None
        except (urllib.error.URLError, OSError):
            raise AppException(502, "SwitchBot could not be reached.") from None

    def _headers(self) -> dict[str, str]:
        """The signature SwitchBot wants on every call: the token, an instant, a nonce.

        Built exactly as their own Python sample builds it. Their prose says to
        upper-case the signature and their sample does not, and base64 is
        case-sensitive, so the two cannot both be what the server checks - the
        sample is the one known to be accepted.
        """
        nonce = str(uuid.uuid4())
        stamp = str(int(time.time() * 1000))
        signed = hmac.new(
            self._secret.encode("utf-8"),
            f"{self._token}{stamp}{nonce}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return {
            "Authorization": self._token,
            "Content-Type": "application/json",
            "charset": "utf8",
            "t": stamp,
            "sign": base64.b64encode(signed).decode("utf-8"),
            "nonce": nonce,
        }

    def _await_slot(self) -> None:
        """A slot under the day's allowance, or the plain truth that there is none.

        Nobody waits out a day, so this asks and gives up at once: the tick says
        so in `last_error` and the next one tries again. The window lives in the
        database because the allowance belongs to the token rather than to a
        process, and at deploy time this app runs as two of them.
        """
        if self._limiter is None:
            return
        if not self._limiter.acquire(self._token, Constants.switchbot_rate_wait_seconds):
            raise AppException(429, "SwitchBot has been asked as many times as the day's allowance permits.")

    @classmethod
    def _refusal(cls, payload: dict[str, Any]) -> str:
        """SwitchBot's own words, which name the device or the parameter at fault."""
        message = str(payload.get("message") or "").strip()
        if not message:
            return f"SwitchBot refused the request (code {payload.get('statusCode')})."
        return f"SwitchBot refused the request: {message[:Constants.switchbot_message_max]}"

    @classmethod
    def _http_failure(cls, error: urllib.error.HTTPError) -> AppException:
        if error.code in (401, 403):
            return AppException(401, "SwitchBot refused the token and secret. Both are copied from the app, Profile, Preferences, Developer Options.")
        if error.code == 429:
            return AppException(429, "SwitchBot is refusing more requests for now.")
        return AppException(502, "SwitchBot could not be reached.")

    @classmethod
    def _json(cls, raw: str) -> dict[str, Any]:
        try:
            result = json.loads(raw)
        except ValueError:
            return {}
        return result if isinstance(result, dict) else {}

    @classmethod
    def _hub_id(cls, raw: Any) -> str:
        """The hub relaying this device, or nothing when the cloud cannot place it.

        A device with no hub says so in two ways - an empty string and twelve
        zeros - and neither of them is an identifier. Both become the same
        nothing here, so one rule covers them everywhere downstream.
        """
        result = str(raw or "").strip()
        return "" if result == Constants.switchbot_zero_hub_id else result

    @classmethod
    def _number(cls, raw: Any) -> float | None:
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
