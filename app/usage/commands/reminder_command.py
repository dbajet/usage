from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from usage.constants.constants import Constants
from usage.libraries.database import Database
from usage.libraries.email_sender import EmailSender
from usage.libraries.email_texts import EmailTexts
from usage.structures.settings import Settings


class ReminderCommand:
    """Sends the monthly reminder email on the first day of the month.

    Reminders are per user and house, enabled by default for every house the
    user is linked to (a user can opt out per house in Settings > Account).
    A background thread checks every hour; each reminder is claimed atomically
    (sent_on) before sending, so restarts and the brief blue/green overlap
    never produce duplicates.
    """

    def __init__(self, database: Database, settings: Settings, email_sender: EmailSender) -> None:
        self._database = database
        self._settings = settings
        self._email_sender = email_sender

    def start(self) -> None:
        thread = threading.Thread(target=self._loop, name="reminders", daemon=True)
        thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exception:  # never let the loop die
                logging.getLogger("usage").warning("[REMINDER] tick failed: %s", exception)
            time.sleep(Constants.reminder_check_seconds)

    def tick(self) -> None:
        today = datetime.now(UTC).date()
        if today.day != 1:
            return
        month_start = today.isoformat()
        previous = today - timedelta(days=1)
        month_label = f"{previous.strftime('%B')} {previous.year}"
        # Reminders default to on: every user/house link gets a row.
        self._database.execute(
            """
            INSERT INTO reminders(user_id, house_id)
            SELECT user_id, house_id FROM user_houses
            ON CONFLICT (user_id, house_id) DO NOTHING
            """,
        )
        rows = self._database.fetch_all(
            """
            SELECT reminders.id, users.email_sealed AS email, houses.name_sealed AS house
            FROM reminders
            JOIN users ON users.id = reminders.user_id
            JOIN houses ON houses.id = reminders.house_id
            WHERE reminders.enabled AND (reminders.sent_on IS NULL OR reminders.sent_on < %s)
            ORDER BY reminders.id
            """,
            (month_start,),
        )
        for row in self._database.decrypt_rows(rows, ("email", "house")):
            claimed = self._database.execute(
                """
                UPDATE reminders SET sent_on = %s
                WHERE id = %s AND (sent_on IS NULL OR sent_on < %s)
                RETURNING id
                """,
                (month_start, int(row["id"]), month_start),
            )
            if not claimed:
                continue
            subject, body_lines = EmailTexts.reminder(month_label, str(row["house"]), self._settings.base_url or "")
            if not self._email_sender.send(str(row["email"]), subject, body_lines):
                logging.getLogger("usage").warning("[REMINDER] email failed for reminder %s", int(row["id"]))
