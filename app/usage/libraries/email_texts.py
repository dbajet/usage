from __future__ import annotations

from usage.constants.constants import Constants
from usage.structures.sensor_breach import SensorBreach
from usage.structures.water_leak import WaterLeak


class EmailTexts:
    """Plain-text email bodies, built as one line per list element."""

    @classmethod
    def sign_in_link(cls, link: str) -> tuple[str, list[str]]:
        subject = f"Your {Constants.app_name} sign-in link"
        body_lines = [
            "Hello,",
            "",
            f"Use this link to sign in to {Constants.app_name}:",
            link,
            "",
            f"The link works once and expires in {Constants.login_link_minutes} minutes.",
            "If you did not request it, you can ignore this email.",
        ]
        return subject, body_lines

    @classmethod
    def reminder(cls, month_label: str, house: str, link: str) -> tuple[str, list[str]]:
        subject = f"{Constants.app_name}: time to record the readings of {house} for {month_label}"
        body_lines = [
            "Hello,",
            "",
            f"A new month has started - a good moment to record the meter readings of {house} for {month_label}:",
            link,
            "",
            "You receive this monthly reminder for this house;",
            "you can turn it off in Settings > Account at any time.",
        ]
        return subject, body_lines

    @classmethod
    def sensor_alert(cls, house: str, breaches: list[SensorBreach], link: str) -> tuple[str, list[str]]:
        """The alert sent when thermometers cross the min or max set for them."""
        alone = len(breaches) == 1
        subject = f"{Constants.app_name}: {breaches[0].name if alone else f'{len(breaches)} sensors'} out of range in {house}"
        opening = "This thermometer" if alone else "These thermometers"
        body_lines = [
            "Hello,",
            "",
            f"{opening} of {house} just went out of the range set for {'it' if alone else 'them'}:",
            "",
        ]
        for breach in breaches:
            side = "below the minimum" if breach.state == Constants.alert_below else "above the maximum"
            unit = f" {breach.unit}" if breach.unit else ""
            body_lines.append(f"- {breach.name}: {breach.value:g}{unit}, {side} of {breach.threshold:g}{unit}")
        # Without a public URL configured there is no link to give, and an empty
        # line in its place would read as a missing one.
        body_lines.extend(["", link] if link else [])
        body_lines.extend([
            "",
            "You receive this alert because you turned threshold alerts on for this house;",
            "you can turn them off in Settings > Sensors at any time.",
        ])
        return subject, body_lines

    @classmethod
    def water_leak(cls, house: str, leak: WaterLeak, link: str) -> tuple[str, list[str]]:
        """The alert sent when 24 hours pass without the water ever stopping."""
        subject = f"{Constants.app_name}: the water never stopped running in {house}"
        body_lines = [
            "Hello,",
            "",
            f"Every one of the last {leak.readings} readings of the water meter of {house} shows water",
            f"flowing - {leak.hours:g} hours without a single quiet moment. A house normally has some:",
            "overnight, or while nobody is in. This usually means a tap, a cistern or a pipe is leaking.",
            "",
            f"- quietest reading in that time: {leak.smallest * 1000:.0f} L",
            f"- drawn in that time: {leak.total:.3f} m3",
            "",
            "It is worth shutting every tap and watching whether the meter still moves.",
        ]
        # Without a public URL configured there is no link to give, and an empty
        # line in its place would read as a missing one.
        body_lines.extend(["", link] if link else [])
        body_lines.extend([
            "",
            "You receive this alert because you turned leak alerts on for this house;",
            "you can turn them off in Settings > Water at any time.",
        ])
        return subject, body_lines

    @classmethod
    def footer(cls, contact: str) -> list[str]:
        return [
            "",
            "—",
            f"{Constants.app_name} · {contact}",
        ]
