from __future__ import annotations

import json
import urllib.error
import urllib.request

from usage.constants.constants import Constants
from usage.structures.app_exception import AppException
from usage.structures.settings import Settings


class MeterReader:
    """Reads the counter value(s) off a meter photo with the Claude API.

    The photo travels in the request and is discarded afterwards - nothing is
    stored. Only the numeric values come back, one per register, for the user
    to confirm in the form.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return bool(self._settings.anthropic_api_key)

    def read(self, image_base64: str, media_type: str, register_labels: list[str]) -> list[float | None]:
        if not self.is_configured():
            raise AppException(503, "Photo extraction is not configured. Enter the value manually.")
        payload = json.dumps(
            {
                "model": self._settings.anthropic_model,
                "max_tokens": Constants.meter_reader_max_tokens,
                # Server-side refusal fallback: on a policy decline the API
                # retries the same request on a fallback model in the same call.
                "fallbacks": "default",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_base64,
                                },
                            },
                            {"type": "text", "text": "\n".join(self._instructions(register_labels))},
                        ],
                    },
                ],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            Constants.anthropic_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._settings.anthropic_api_key,
                "anthropic-version": Constants.anthropic_version,
                "anthropic-beta": Constants.anthropic_beta_fallbacks,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=Constants.meter_reader_timeout_seconds) as response:  # noqa: S310
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            raise AppException(502, "The photo could not be analyzed. Try again or enter the value manually.") from None
        return self._values(data, len(register_labels))

    @classmethod
    def _instructions(cls, register_labels: list[str]) -> list[str]:
        named = [label or f"register {position + 1}" for position, label in enumerate(register_labels)]
        return [
            "You are reading a photo of a utility meter (or a car odometer).",
            f"The meter has {len(named)} register(s), in this order: {', '.join(named)}.",
            "Read the current counter value of each register from the photo.",
            "Ignore serial numbers, dates, units, and any digits after a decimal marker painted in red.",
            'Reply with ONLY this JSON, nothing else: {"values": [...]}',
            "with one number per register in the order above, or null when a register cannot be read.",
        ]

    @classmethod
    def _values(cls, data: dict[str, object], count: int) -> list[float | None]:
        if str(data.get("stop_reason") or "") == "refusal":
            raise AppException(502, "The photo could not be analyzed. Try again or enter the value manually.")
        content = data.get("content")
        text = ""
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "")
                break
        stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            values = json.loads(stripped).get("values")
        except (ValueError, AttributeError):
            raise AppException(502, "The photo could not be analyzed. Try again or enter the value manually.") from None
        if not isinstance(values, list) or len(values) != count:
            raise AppException(502, "The photo could not be analyzed. Try again or enter the value manually.")
        result: list[float | None] = []
        for value in values:
            result.append(float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
        return result
