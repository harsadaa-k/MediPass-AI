"""
Day counts for treatment courses and follow-ups.

Prescriptions write durations many ways ("x 10 days", "for 1 week",
"1-0-1 for 5 days", "2/52", "3 months"). This module turns them into a
number of days and a calendar end date, counted inclusively from the
consultation date: a 10-day course starting 31 May 2025 ends 9 June 2025.

Months and years are calendar-based, so leap years come out right:
1 month from 31 Jan 2024 ends 29 Feb 2024 (30 days); from 31 Jan 2023 it
ends 28 Feb 2023 (29 days). All arithmetic is on plain dates (no times),
so time zones can't shift a count by a day.
"""
import calendar
import re
from datetime import date, timedelta
from typing import Optional

_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30,
}
_NUM = r"(\d{1,3}|" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")"
_UNIT = r"(days?|d|din|weeks?|wks?|w|months?|mon|mths?|mo|years?|yrs?|y)"
# "x 10 days", "for 5 days", "* 1 week", "10 days", "x10d"
_DURATION = re.compile(r"(?:\b(?:x|for)\s*|[×*]\s*|\b)" + _NUM + r"\s*" + _UNIT + r"\b", re.I)
# Medical shorthand: 5/7 = 5 days, 2/52 = 2 weeks, 3/12 = 3 months
_SHORTHAND = re.compile(r"\b(\d{1,2})\s*/\s*(7|52|12)\b")
_ONGOING = re.compile(r"\b(continue|cont\.?|long[- ]term|lifelong|till next (?:visit|review)|until further)\b", re.I)
_AS_NEEDED = re.compile(r"\b(sos|as needed|as required|prn|when required)\b", re.I)
# "follow up after 2 weeks", "review in 10 days", "revisit after 1 month"
_FOLLOW_UP_REL = re.compile(r"\b(?:follow[- ]?up|review|revisit|recheck|come back|f/u)\b[^.\n]{0,25}?\b(?:after|in)\s+" + _NUM + r"\s*" + _UNIT + r"\b", re.I)
# "follow up on 15/06/2025", "review on 5-7-25"
_FOLLOW_UP_DATE = re.compile(r"\b(?:follow[- ]?up|review|revisit|f/u)\b[^.\n]{0,25}?\b(?:on|by|date)?\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", re.I)


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _WORD_NUMBERS[token.lower()]


def _unit(token: str) -> str:
    t = token.lower()
    if t.startswith("y"):
        return "years"
    if t.startswith("mo") or t.startswith("mth") or t == "mon":
        return "months"
    if t.startswith("w"):
        return "weeks"
    return "days"


def add_months(start: date, months: int) -> date:
    """Same day `months` later; if that day doesn't exist (31 Jan + 1 month),
    roll to the 1st of the following month."""
    y, m = divmod(start.month - 1 + months, 12)
    year, month = start.year + y, m + 1
    last = calendar.monthrange(year, month)[1]
    if start.day <= last:
        return date(year, month, start.day)
    return date(year, month, last) + timedelta(days=1)


def _advance(start: date, amount: int, unit: str) -> date:
    """The day after the period ends (exclusive end)."""
    if unit == "days":
        return start + timedelta(days=amount)
    if unit == "weeks":
        return start + timedelta(weeks=amount)
    if unit == "months":
        return add_months(start, amount)
    return add_months(start, 12 * amount)


def parse_duration(text: str) -> Optional[tuple]:
    """(amount, unit) for the first duration in `text`, e.g. (10, "days")."""
    if not text:
        return None
    m = _DURATION.search(text)
    if m:
        amount = _number(m.group(1))
        if 0 < amount <= 3650:
            return amount, _unit(m.group(2))
    m = _SHORTHAND.search(text)
    if m and 0 < int(m.group(1)) < 100:
        return int(m.group(1)), {"7": "days", "52": "weeks", "12": "months"}[m.group(2)]
    return None


def format_duration(amount: int, unit: str) -> str:
    return f"{amount} {unit[:-1] if amount == 1 else unit}"


def medication_course(details: dict, start: date) -> Optional[dict]:
    """
    The treatment course of a medication record, or None if the prescription
    gives no duration. Looks at details.duration first, then timing and
    notes ("1-0-1 for 5 days", "x 10 days").
    """
    if not isinstance(details, dict) or start is None:
        return None
    fields = [details.get(k) for k in ("duration", "timing", "notes", "raw_line")]
    texts = [str(t) for t in fields if t]
    for text in texts:
        parsed = parse_duration(text)
        if parsed:
            amount, unit = parsed
            end_exclusive = _advance(start, amount, unit)
            return {
                "duration": format_duration(amount, unit),
                "duration_days": (end_exclusive - start).days,
                "start_date": start.isoformat(),
                "end_date": (end_exclusive - timedelta(days=1)).isoformat(),
                "ongoing": False,
            }
    for pattern, label in ((_ONGOING, "ongoing"), (_AS_NEEDED, "as needed")):
        if any(pattern.search(t) for t in texts):
            return {"duration": label, "duration_days": None,
                    "start_date": start.isoformat(), "end_date": None, "ongoing": True}
    return None


def _parse_day_first(d: str, m: str, y: str) -> Optional[date]:
    year = int(y)
    if year < 100:
        year += 2000
    try:
        return date(year, int(m), int(d))
    except ValueError:
        return None


def follow_up_due(text: str, note_date: date) -> Optional[date]:
    """Date a follow-up is due, from 'review after 2 weeks' or 'follow up on
    15/06/2025' (day/month/year), counted from the note's date."""
    if not text or note_date is None:
        return None
    m = _FOLLOW_UP_DATE.search(text)
    if m:
        due = _parse_day_first(*m.groups())
        if due:
            return due
    m = _FOLLOW_UP_REL.search(text)
    if m:
        return _advance(note_date, _number(m.group(1)), _unit(m.group(2)))
    return None
