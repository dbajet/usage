from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SwitchBotEventRequest(BaseModel):
    """What SwitchBot posts to the webhook, in their shape rather than ours.

    Nothing signs it - they document no signature at all - so the URL carries
    the secret and the body is treated as something a stranger could have sent:
    the device has to be one this house already collects, or the event is
    dropped.
    """

    eventType: str = ""
    eventVersion: str = ""
    context: dict[str, Any] = {}
