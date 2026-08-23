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
    """Sends the opt-in monthly reminder email on the first day of the month.

    A background thread checks every hour; each user is claimed atomically
    (reminder_sent_on) before sending, so restarts and the brief blue/green
    overlap never produce duplicates.
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
        rows = self._database.fetch_all(
            """
            SELECT id, email_sealed AS email FROM users
            WHERE reminder AND (reminder_sent_on IS NULL OR reminder_sent_on < %s)
            ORDER BY id
            """,
            (month_start,),
        )
        for row in self._database.decrypt_rows(rows, ("email",)):
            claimed = self._database.execute(
                """
                UPDATE users SET reminder_sent_on = %s
                WHERE id = %s AND (reminder_sent_on IS NULL OR reminder_sent_on < %s)
                RETURNING id
                """,
                (month_start, int(row["id"]), month_start),
            )
            if not claimed:
                continue
            subject, body_lines = EmailTexts.reminder(month_label, self._settings.base_url or "")
            if not self._email_sender.send(str(row["email"]), subject, body_lines):
                logging.getLogger("usage").warning("[REMINDER] email failed for user %s", int(row["id"]))
