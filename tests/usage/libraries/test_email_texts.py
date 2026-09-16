from __future__ import annotations

from usage.libraries.email_texts import EmailTexts
from usage.structures.sensor_breach import SensorBreach
from usage.structures.water_window import WaterWindow


def test_sign_in_link() -> None:
    tested = EmailTexts
    result = tested.sign_in_link("https://usage.example.com/?login=theToken")
    expected = (
        "Your Usage sign-in link",
        [
            "Hello,",
            "",
            "Use this link to sign in to Usage:",
            "https://usage.example.com/?login=theToken",
            "",
            "The link works once and expires in 15 minutes.",
            "If you did not request it, you can ignore this email.",
        ],
    )
    assert result == expected


def test_reminder() -> None:
    tested = EmailTexts
    result = tested.reminder("August 2026", "Fremur", "https://usage.example.com")
    expected = (
        "Usage: time to record the readings of Fremur for August 2026",
        [
            "Hello,",
            "",
            "A new month has started - a good moment to record the meter readings of Fremur for August 2026:",
            "https://usage.example.com",
            "",
            "You receive this monthly reminder for this house;",
            "you can turn it off in Settings > Account at any time.",
        ],
    )
    assert result == expected


def test_sensor_alert() -> None:
    tested = EmailTexts
    below = SensorBreach(sensor_id=3, name="Freezer", value=12.5, unit="°F", state="below", threshold=15.0)
    above = SensorBreach(sensor_id=4, name="Grenier", value=91.0, unit="°F", state="above", threshold=85.0)
    nameless = SensorBreach(sensor_id=5, name="Cave", value=2.0, unit="", state="above", threshold=1.5)

    result = tested.sensor_alert("Fremur", [below], "https://usage.example.com")
    expected = (
        "Usage: Freezer out of range in Fremur",
        [
            "Hello,",
            "",
            "This thermometer of Fremur just went out of the range set for it:",
            "",
            "- Freezer: 12.5 °F, below the minimum of 15 °F",
            "",
            "https://usage.example.com",
            "",
            "You receive this alert because you turned threshold alerts on for this house;",
            "you can turn them off in Settings > Sensors at any time.",
        ],
    )
    assert result == expected

    result = tested.sensor_alert("Fremur", [below, above, nameless], "")
    expected = (
        "Usage: 3 sensors out of range in Fremur",
        [
            "Hello,",
            "",
            "These thermometers of Fremur just went out of the range set for them:",
            "",
            "- Freezer: 12.5 °F, below the minimum of 15 °F",
            "- Grenier: 91 °F, above the maximum of 85 °F",
            "- Cave: 2, above the maximum of 1.5",
            "",
            "You receive this alert because you turned threshold alerts on for this house;",
            "you can turn them off in Settings > Sensors at any time.",
        ],
    )
    assert result == expected


def test_water_leak() -> None:
    tested = EmailTexts
    leak = WaterWindow(feed_id=11, readings=96, hours=23.8, smallest=0.0034, total=0.4123)

    result = tested.water_leak("Dougmar", leak, "https://usage.example.com")
    expected = (
        "Usage: the water never stopped running in Dougmar",
        [
            "Hello,",
            "",
            "Every one of the last 96 readings of the water meter of Dougmar shows water",
            "flowing - 23.8 hours without a single quiet moment. A house normally has some:",
            "overnight, or while nobody is in. This usually means a tap, a cistern or a pipe is leaking.",
            "",
            "- quietest reading in that time: 3 L",
            "- drawn in that time: 0.412 m3",
            "",
            "It is worth shutting every tap and watching whether the meter still moves.",
            "",
            "https://usage.example.com",
            "",
            "You receive this alert because you turned leak alerts on for this house;",
            "you can turn them off in Settings > Water at any time.",
        ],
    )
    assert result == expected

    # without a public URL there is no link to give, and no blank line for it either
    result = tested.water_leak("Dougmar", leak, "")
    assert "https://usage.example.com" not in result[1]
    assert result[1][-4] == "It is worth shutting every tap and watching whether the meter still moves."


def test_water_over() -> None:
    tested = EmailTexts
    window = WaterWindow(feed_id=11, readings=96, hours=23.8, smallest=0.0034, total=0.9123)

    result = tested.water_over("Dougmar", window, 0.5, "https://usage.example.com")
    expected = (
        "Usage: Dougmar used more water than usual",
        [
            "Hello,",
            "",
            "The water meter of Dougmar drew 912 L over the last 23.8 hours,",
            "which is above the 500 L you set as this meter's limit for any 24 hours.",
            "",
            "- drawn in that time: 0.912 m3",
            "- the limit: 0.500 m3",
            "- readings counted: 96",
            "",
            "A run of watering or a houseful of guests will do this quite innocently.",
            "Worth a look if neither applies.",
            "",
            "https://usage.example.com",
            "",
            "You receive this alert because you turned water alerts on for this house;",
            "you can turn them off in Settings > Water at any time.",
        ],
    )
    assert result == expected

    # without a public URL there is no link to give, and no blank line for it either
    result = tested.water_over("Dougmar", window, 0.5, "")
    assert "https://usage.example.com" not in result[1]
    assert result[1][-4] == "Worth a look if neither applies."


def test_footer() -> None:
    tested = EmailTexts
    result = tested.footer("usage@edgy.world")
    expected = [
        "",
        "—",
        "Usage · usage@edgy.world",
    ]
    assert result == expected
