from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Any

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.rate_limiter import RateLimiter
from usage.libraries.switch_bot_client import SwitchBotClient
from usage.libraries.switch_bot_hubs import SwitchBotHubs
from usage.structures.app_exception import AppException
from usage.structures.session_user import SessionUser
from usage.structures.settings import Settings


class SwitchBotCommand:
    """The SwitchBot cloud feeds of a house: whose account, and which hubs of it.

    A house with no Home Assistant has nothing to push its thermometers, so the
    app pulls them instead. The one thing it has to be told is which of the
    account's devices stand in this house, and the answer is the hub: SwitchBot's
    own "Homes" never cross the API boundary, while every device names the hub
    that relays it - and a hub is a box in a room, which is exactly the question.

    So a hub is what is picked, never a device. A device list is a snapshot and a
    hub is a standing answer: a thermometer paired next year is relayed by the
    same hub and appears on its own, where a ticked list of devices would
    silently miss it and look like a thermometer that had stopped working.

    Creating a feed asks the account for its devices first, which proves the
    token and the secret in the form rather than hours later in `last_error` -
    the same call the sync makes, so nothing is tested that is not used.
    """

    def __init__(self, database: Database, settings: Settings, limiter: RateLimiter) -> None:
        self._database = database
        self._settings = settings
        self._limiter = limiter

    def hubs(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        """What an account has, grouped by the hub relaying it, for the picker.

        Every device is listed under its hub and not only the thermometers:
        recognising which hub is which is the whole point, and "Grenier,
        Dehors, Freezer" is what makes that obvious to the person choosing.
        """
        house_id = int(data.get("house_id") or 0)
        self._require_admin(user)
        self._require_house(user, house_id)
        token, secret = self._credentials(data)
        return {"hubs": self._picker(token, secret)}

    def feed_hubs(self, user: SessionUser, feed_id: int) -> dict[str, Any]:
        """The same picker for a feed already stored, on the credentials it holds.

        Editing one is mostly moving a hub, and the token and secret are never
        sent back to the browser - so the account is asked from here rather than
        made to be typed again for the sake of a tick box.
        """
        self._require_admin(user)
        feed = self._require_feed(user, feed_id)
        token = self._database.decrypt(str(feed["token"]))
        secret = self._database.decrypt(str(feed["secret"]))
        return {"hubs": self._picker(token, secret)}

    def list_feeds(self, user: SessionUser, house_id: int) -> dict[str, Any]:
        self._require_admin(user)
        self._require_house(user, house_id)
        feeds = self._database.decrypt_rows(
            self._database.fetch_all(
                """
                SELECT id, token_sealed AS token, hub_ids_sealed AS hub_ids, active,
                       last_sync_at, last_point_at, last_error, webhook_at, webhook_error,
                       last_event_at, created_at
                FROM switchbot_feeds WHERE house_id = %s ORDER BY id
                """,
                (house_id,),
            ),
            ("token", "hub_ids"),
        )
        result: list[dict[str, Any]] = []
        for feed in feeds:
            hub_ids = self._split(str(feed["hub_ids"]))
            result.append(
                {
                    "id": int(feed["id"]),
                    # Enough of the token to tell two accounts apart, and no more:
                    # it is a credential, and the form never shows it again.
                    "token_tail": str(feed["token"])[-Constants.switchbot_token_tail:],
                    "hub_ids": list(hub_ids),
                    "active": bool(feed["active"]),
                    "last_sync_at": self._moment(feed["last_sync_at"]),
                    "last_point_at": self._moment(feed["last_point_at"]),
                    "last_error": str(feed["last_error"]),
                    # Registered is not the same as working: SwitchBot accepting
                    # the URL says nothing about whether anything has come back
                    # through it, and only the second one is proof.
                    "webhook_at": self._moment(feed["webhook_at"]),
                    "webhook_error": str(feed["webhook_error"]),
                    "last_event_at": self._moment(feed["last_event_at"]),
                },
            )
        return {"feeds": result}

    def create_feed(self, user: SessionUser, data: dict[str, Any]) -> dict[str, Any]:
        house_id = int(data.get("house_id") or 0)
        self._require_admin(user)
        self._require_house(user, house_id)
        token, secret = self._credentials(data)
        hub_ids = self._resolve_hubs(self._hubs_of(token, secret), data)
        existing = self._database.fetch_one("SELECT id FROM switchbot_feeds WHERE house_id = %s", (house_id,))
        if existing is not None:
            # One account per house, which is what the house's own settings
            # dialog offers: a second would be a feed nothing on that screen
            # could show, let alone edit.
            raise AppException(409, "This house already collects from a SwitchBot account. Edit that one instead.")
        # The secret in the URL SwitchBot will post events to. Generated here
        # and never typed: nothing signs those posts, so this is what stands
        # between the endpoint and anybody who finds it.
        event_token = secrets.token_urlsafe(Constants.switchbot_event_token_bytes)
        feed_id = self._database.execute(
            """
            INSERT INTO switchbot_feeds(house_id, token_sealed, token_hash, secret_sealed, hub_ids_sealed,
                                        event_token_sealed, event_token_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                house_id,
                self._database.encrypt(token),
                self._database.blind_index(token),
                self._database.encrypt(secret),
                self._database.encrypt(",".join(hub_ids)),
                self._database.encrypt(event_token),
                self._database.blind_index(event_token),
            ),
        )
        return {"id": feed_id, "message": "SwitchBot feed added. The first readings arrive within a minute."}

    def update_feed(self, user: SessionUser, feed_id: int, data: dict[str, Any]) -> dict[str, str]:
        self._require_admin(user)
        feed = self._require_feed(user, feed_id)
        token = str(data.get("token") or "").strip() or self._database.decrypt(str(feed["token"]))
        # An empty secret means "keep the one already stored": it is never sent
        # back to the browser, so an edit that only moves a hub cannot retype it.
        secret = str(data.get("secret") or "").strip() or self._database.decrypt(str(feed["secret"]))
        hub_ids = self._resolve_hubs(self._hubs_of(token, secret), data)
        self._database.execute(
            """
            UPDATE switchbot_feeds
            SET token_sealed = %s, token_hash = %s, secret_sealed = %s, hub_ids_sealed = %s,
                active = %s, last_error = ''
            WHERE id = %s
            """,
            (
                self._database.encrypt(token),
                self._database.blind_index(token),
                self._database.encrypt(secret),
                self._database.encrypt(",".join(hub_ids)),
                bool(data.get("active")),
                feed_id,
            ),
        )
        return {"message": "SwitchBot feed updated."}

    def delete_feed(self, user: SessionUser, feed_id: int) -> dict[str, str]:
        """Stop pulling; the thermometers and their history stay where they are.

        Unlike a water feed, whose readings hang off it and go with it, what
        this collects lives in the house's own sensors. Deleting the feed only
        stops the asking - a year of temperatures is not thrown away because an
        account was swapped, and a sensor nobody wants any more is hidden in
        Settings, Sensors like any other.
        """
        self._require_admin(user)
        feed = self._require_feed(user, feed_id)
        self._unregister(feed)
        self._database.execute("DELETE FROM switchbot_feeds WHERE id = %s", (feed_id,))
        return {"message": "SwitchBot feed deleted. The thermometers it collected keep everything they have."}

    def _unregister(self, feed: dict[str, Any]) -> None:
        """Ask SwitchBot to stop posting to a URL that is about to stop existing.

        Best effort on purpose. A feed being deleted is going whatever they say,
        and an account that cannot be reached must not leave it half removed -
        the URL answers nothing once the row is gone.
        """
        event_token = self._database.decrypt(str(feed["event_token"]))
        url = self._event_url(event_token)
        if not url:
            return
        try:
            client = SwitchBotClient(
                self._database.decrypt(str(feed["token"])),
                self._database.decrypt(str(feed["secret"])),
                self._limiter,
            )
            client.delete_webhook(url)
        except AppException as exception:
            logging.getLogger("usage").info("[SWITCHBOT] webhook not withdrawn: %s", exception.message)

    def _event_url(self, event_token: str) -> str:
        """Where SwitchBot posts this feed's events, when the app has an address for it."""
        base = (self._settings.base_url or "").strip().rstrip("/")
        if not event_token or not base.startswith(Constants.switchbot_webhook_scheme):
            return ""
        return f"{base}{Constants.switchbot_event_path}{event_token}"

    def _picker(self, token: str, secret: str) -> list[dict[str, Any]]:
        """What the account has, ready to be ticked, as places rather than devices."""
        return [hub.to_dict() for hub in self._hubs_of(token, secret).groups()]

    def _hubs_of(self, token: str, secret: str) -> SwitchBotHubs:
        """Read the account once, the one way both the picker and the sync read it.

        An empty account is said out loud here rather than left to the picker,
        where it would arrive as a dialog with nothing in it and no explanation.
        """
        devices = SwitchBotClient(token, secret, self._limiter).devices()
        if not devices:
            raise AppException(502, "That SwitchBot account has no device on it.")
        return SwitchBotHubs(devices)

    def _resolve_hubs(self, hubs: SwitchBotHubs, data: dict[str, Any]) -> list[str]:
        """The hubs to follow, checked against the places the account actually reaches."""
        wanted = [str(hub_id).strip() for hub_id in data.get("hub_ids") or [] if str(hub_id).strip()]
        if not wanted:
            raise AppException(400, "Choose at least one hub: its devices are what this house collects.")
        known = {hub.hub_id for hub in hubs.groups()}
        missing = [hub_id for hub_id in wanted if hub_id not in known]
        if missing:
            raise AppException(400, f"This account has nothing behind {', '.join(missing)} any more.")
        # Ordered and deduplicated, so two feeds picking the same hubs in a
        # different order store the same thing.
        return sorted(set(wanted))

    @classmethod
    def _credentials(cls, data: dict[str, Any]) -> tuple[str, str]:
        token = str(data.get("token") or "").strip()
        secret = str(data.get("secret") or "").strip()
        if not token or not secret:
            raise AppException(400, "Enter the SwitchBot token and secret, both from the app's Developer Options.")
        return token, secret

    @classmethod
    def _split(cls, sealed: str) -> tuple[str, ...]:
        return tuple(part for part in sealed.split(",") if part)

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
            "SELECT id, house_id, token_sealed AS token, secret_sealed AS secret, "
            "event_token_sealed AS event_token FROM switchbot_feeds WHERE id = %s",
            (feed_id,),
        )
        if result is None:
            raise AppException(404, "The SwitchBot feed was not found.")
        if int(result["house_id"]) not in self._visible_house_ids(user):
            raise AppException(403, "You do not have access to this house.")
        return result
