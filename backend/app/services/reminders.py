"""When a reminder fires, and when the next one does.

One rule underlies the whole module: **advance in local-date space, then
convert**. Adding a day to a UTC instant adds twenty-four hours, which is a
different wall clock on either side of a daylight-saving change - a "9am
daily" reminder silently becomes 8am in October and nobody can say why.

The second rule is that every occurrence is derived from the *anchor*, never
from the one before it. Otherwise a monthly reminder on the 31st lands on the
28th in February and then stays on the 28th for ever, having quietly forgotten
what it was for.
"""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import NoteReminder, ReminderEnds, ReminderRecurrence


def is_valid_timezone(name: str) -> bool:
    """Whether this is a zone the machine actually knows.

    Checked at the API boundary, because an unknown name is otherwise a
    `ZoneInfoNotFoundError` raised inside the worker at nine in the morning.
    """
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        return False
    return True


def instant_for(local_date: date, local_time: time, tz_name: str) -> datetime:
    """The UTC instant a wall clock reading names in a zone.

    Two things the calendar does that a clock does not:

    * **Spring forward** deletes an hour, so a 02:30 reminder on that date names
      a time that does not exist. It fires at the first instant that does -
      03:00 - rather than an hour early, which is what naive conversion gives.
    * **Autumn back** repeats an hour, so 02:30 happens twice. It fires on the
      first. Once, earlier, and written down here so nobody has to guess.
    """
    zone = ZoneInfo(tz_name)
    naive = datetime.combine(local_date, local_time)
    aware = naive.replace(tzinfo=zone, fold=0)

    # A local time inside a gap does not survive the round trip.
    if aware.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive:
        return aware.astimezone(UTC)

    # Walk to the far side of the gap. Gaps are an hour or two at most; the
    # bound is a whole day so a pathological zone cannot spin.
    for minutes in range(1, 24 * 60):
        moved = naive + timedelta(minutes=minutes)
        probe = moved.replace(tzinfo=zone, fold=0)
        if probe.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == moved:
            return probe.astimezone(UTC)
    return aware.astimezone(UTC)


def _clamp_day(year: int, month: int, day: int) -> date:
    """The given day of that month, or its last day when it is shorter."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_local_date(reminder: NoteReminder, after: date) -> date | None:
    """The next occurrence's local date, or None when the rule has run out.

    Derived from `anchor_date` every time. That is the difference between a
    monthly reminder on the 31st returning to the 31st in March and one that
    ratchets down to the 28th and stays there.
    """
    anchor = reminder.anchor_date
    rule = reminder.recurrence

    if rule == ReminderRecurrence.none:
        return None

    if rule == ReminderRecurrence.daily:
        candidate = after + timedelta(days=1)
    elif rule == ReminderRecurrence.weekly:
        ahead = (anchor.weekday() - after.weekday()) % 7 or 7
        candidate = after + timedelta(days=ahead)
    elif rule == ReminderRecurrence.monthly:
        year, month = after.year, after.month
        candidate = _clamp_day(year, month, anchor.day)
        if candidate <= after:
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            candidate = _clamp_day(year, month, anchor.day)
    elif rule == ReminderRecurrence.yearly:
        candidate = _clamp_day(after.year, anchor.month, anchor.day)
        if candidate <= after:
            candidate = _clamp_day(after.year + 1, anchor.month, anchor.day)
    else:  # pragma: no cover - the enum has no other members
        return None

    if reminder.ends == ReminderEnds.on_date and reminder.ends_on is not None:
        if candidate > reminder.ends_on:
            return None
    if reminder.ends == ReminderEnds.after and reminder.ends_after is not None:
        if reminder.sent_count >= reminder.ends_after:
            return None
    return candidate


def describe(reminder: NoteReminder) -> str:
    """The whole rule in one sentence, for the email's footer."""
    when = reminder.local_time.strftime("%H:%M")
    if reminder.recurrence == ReminderRecurrence.none:
        return f"once, at {when}"
    every = {
        ReminderRecurrence.daily: "every day",
        ReminderRecurrence.weekly: f"every {reminder.anchor_date.strftime('%A')}",
        ReminderRecurrence.monthly: f"on the {reminder.anchor_date.day}th of each month",
        ReminderRecurrence.yearly: f"every {reminder.anchor_date.strftime('%-d %B')}",
    }[reminder.recurrence]
    sentence = f"{every} at {when}"
    if reminder.ends == ReminderEnds.on_date and reminder.ends_on:
        sentence += f", until {reminder.ends_on.strftime('%-d %B %Y')}"
    if reminder.ends == ReminderEnds.after and reminder.ends_after:
        sentence += f", {reminder.ends_after} times in all"
    return sentence
