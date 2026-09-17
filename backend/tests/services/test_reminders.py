"""Recurrence, across the awkward parts of the calendar.

Every case here is one somebody has shipped wrong. A daily reminder that
quietly moves an hour in October; a monthly one that falls off the end of
February and never climbs back; a yearly one set on a leap day. They are cheap
to test and expensive to discover.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from app.models import NoteReminder, ReminderEnds, ReminderRecurrence
from app.services.reminders import (
    describe,
    instant_for,
    is_valid_timezone,
    next_local_date,
)


def reminder(**overrides) -> NoteReminder:  # type: ignore[no-untyped-def]
    base = {
        "note_id": None,
        "user_id": None,
        "local_time": time(9, 0),
        "timezone": "Europe/Berlin",
        "anchor_date": date(2026, 1, 15),
        "recurrence": ReminderRecurrence.daily,
        "ends": ReminderEnds.never,
        "next_run_at": None,
        "next_local_date": date(2026, 1, 15),
    }
    base.update(overrides)
    return NoteReminder.model_construct(**base)  # type: ignore[arg-type]


# --- zones ------------------------------------------------------------------


def test_an_unknown_zone_is_rejected_rather_than_raised_at_nine_am() -> None:
    assert is_valid_timezone("Europe/Berlin")
    assert not is_valid_timezone("Middle/Earth")


@pytest.mark.parametrize(
    ("zone", "winter_utc", "summer_utc"),
    [
        # Northern hemisphere: the offset grows in summer.
        ("Europe/Berlin", 8, 7),
        # Southern hemisphere, where the seasons are the other way round.
        ("America/Santiago", 12, 13),
    ],
)
def test_nine_in_the_morning_stays_nine_in_the_morning(
    zone: str, winter_utc: int, summer_utc: int
) -> None:
    """The whole reason a wall clock is stored instead of an instant."""
    january = instant_for(date(2026, 1, 15), time(9, 0), zone)
    july = instant_for(date(2026, 7, 15), time(9, 0), zone)

    assert january.hour == winter_utc
    assert july.hour == summer_utc
    # Different instants, same reading on the wall - which is what was asked for.
    assert january.hour != july.hour


def test_a_time_that_does_not_exist_fires_at_the_first_one_that_does() -> None:
    """Spring forward deletes an hour; 02:30 that night is not a time.

    Naive conversion answers 01:30 UTC, which is an hour early. This walks to
    the far side of the gap instead.
    """
    # Europe/Berlin springs forward at 02:00 on 29 March 2026.
    fired = instant_for(date(2026, 3, 29), time(2, 30), "Europe/Berlin")
    local = fired.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
    assert local.hour == 3, "should land on the far side of the gap"


def test_a_repeated_hour_fires_once_on_the_first() -> None:
    """Autumn back repeats an hour. Firing twice would be the worse answer."""
    fired = instant_for(date(2026, 10, 25), time(2, 30), "Europe/Berlin")
    # The earlier of the two 02:30s is still +02:00.
    assert fired.hour == 0


# --- recurrence -------------------------------------------------------------


def test_daily_advances_a_local_day_not_a_fixed_span() -> None:
    assert next_local_date(reminder(), date(2026, 3, 28)) == date(2026, 3, 29)


def test_weekly_returns_to_the_anchors_weekday() -> None:
    # 15 January 2026 is a Thursday.
    r = reminder(recurrence=ReminderRecurrence.weekly)
    assert next_local_date(r, date(2026, 1, 15)) == date(2026, 1, 22)
    assert next_local_date(r, date(2026, 1, 18)) == date(2026, 1, 22)


def test_monthly_on_the_31st_climbs_back_out_of_february() -> None:
    """The bug this design exists to avoid.

    Derived from the previous occurrence, a 31st reminder clamps to 28 February
    and then stays on the 28th for the rest of its life. Derived from the
    anchor, February is the only month it is short.
    """
    r = reminder(recurrence=ReminderRecurrence.monthly, anchor_date=date(2026, 1, 31))
    february = next_local_date(r, date(2026, 1, 31))
    assert february == date(2026, 2, 28)

    march = next_local_date(r, february)
    assert march == date(2026, 3, 31), "it must return to the 31st"


def test_yearly_on_a_leap_day_survives_the_common_years() -> None:
    r = reminder(recurrence=ReminderRecurrence.yearly, anchor_date=date(2024, 2, 29))
    assert next_local_date(r, date(2024, 2, 29)) == date(2025, 2, 28)
    # And is back on the 29th when there is one again.
    assert next_local_date(r, date(2027, 3, 1)) == date(2028, 2, 29)


def test_a_one_off_has_no_next() -> None:
    assert (
        next_local_date(reminder(recurrence=ReminderRecurrence.none), date(2026, 1, 15))
        is None
    )


def test_it_stops_on_the_end_date() -> None:
    r = reminder(ends=ReminderEnds.on_date, ends_on=date(2026, 1, 16))
    assert next_local_date(r, date(2026, 1, 15)) == date(2026, 1, 16)
    assert next_local_date(r, date(2026, 1, 16)) is None


def test_it_stops_after_a_count() -> None:
    r = reminder(ends=ReminderEnds.after, ends_after=3, sent_count=3)
    assert next_local_date(r, date(2026, 1, 15)) is None


def test_the_rule_reads_as_a_sentence() -> None:
    """The one control that actually prevents a mistake in the dialog."""
    weekly = reminder(
        recurrence=ReminderRecurrence.weekly,
        ends=ReminderEnds.on_date,
        ends_on=date(2027, 3, 12),
    )
    assert describe(weekly) == "every Thursday at 09:00, until 12 March 2027"
    assert describe(reminder(recurrence=ReminderRecurrence.none)) == "once, at 09:00"
