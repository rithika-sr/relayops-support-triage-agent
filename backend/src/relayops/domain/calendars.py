"""Service calendars: weekly service hours in an IANA time zone, with holidays.

Elapsed service time is counted only inside service windows, evaluated in the calendar's local time. Each
day's windows are converted to UTC through zoneinfo, so a 09:00-17:00 window stays 09:00-17:00 local across
DST changes (its UTC offset moves) and a window that touches a skipped or repeated hour has its real length.
Results are always UTC; callers persist them with the calendar version that produced them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$")
MAX_SEARCH_DAYS = 400


class CalendarError(ValueError):
    pass


def _t(s: str) -> time:
    if s == "24:00":
        return time.max
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Calendar:
    name: str
    version: int
    timezone: str
    weekly: dict[str, list[tuple[str, str]]]
    holidays: frozenset[date] = field(default_factory=frozenset)

    @property
    def ref(self) -> str:
        return f"{self.name}@v{self.version}"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def windows_utc(self, day: date) -> list[tuple[datetime, datetime]]:
        """This local day's service windows as UTC intervals (empty on holidays and closed days)."""
        if day in self.holidays:
            return []
        out = []
        for start, end in self.weekly.get(DAYS[day.weekday()], []):
            s = datetime.combine(day, _t(start), self.tz)
            e = (
                datetime.combine(day + timedelta(days=1), time(0), self.tz)
                if end == "24:00"
                else (datetime.combine(day, _t(end), self.tz))
            )
            # Normalize through UTC: a wall time inside a spring-forward gap maps to the instant after the gap.
            su, eu = s.astimezone(UTC), e.astimezone(UTC)
            if eu > su:
                out.append((su, eu))
        return out


def validate(
    timezone: str, weekly: dict[str, Any], holidays: list[str]
) -> tuple[dict[str, list[tuple[str, str]]], frozenset[date]]:
    if timezone not in available_timezones():
        raise CalendarError(f"unknown IANA time zone: {timezone}")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise CalendarError(f"unknown IANA time zone: {timezone}") from exc
    clean: dict[str, list[tuple[str, str]]] = {}
    for day, wins in weekly.items():
        if day not in DAYS:
            raise CalendarError(f"unknown day {day!r}; use {', '.join(DAYS)}")
        parsed = []
        for w in wins:
            if not (
                isinstance(w, list | tuple) and len(w) == 2 and all(isinstance(x, str) and HHMM.match(x) for x in w)
            ):
                raise CalendarError(f'{day}: windows are ["HH:MM", "HH:MM"] pairs')
            if _t(w[1]) <= _t(w[0]):
                raise CalendarError(f"{day}: window {w[0]}-{w[1]} must end after it starts")
            parsed.append((w[0], w[1]))
        parsed.sort()
        for a, b in zip(parsed, parsed[1:], strict=False):
            if _t(b[0]) < _t(a[1]):
                raise CalendarError(f"{day}: windows {a[0]}-{a[1]} and {b[0]}-{b[1]} overlap")
        clean[day] = parsed
    if not any(clean.values()):
        raise CalendarError("a calendar needs at least one service window")
    try:
        days = frozenset(date.fromisoformat(h) for h in holidays)
    except ValueError as exc:
        raise CalendarError(f"holidays must be YYYY-MM-DD: {exc}") from exc
    return clean, days


def add_service_time(cal: Calendar, start: datetime, duration: timedelta) -> datetime:
    """The UTC instant when `duration` of service time has elapsed after `start`."""
    if start.tzinfo is None:
        raise CalendarError("start must be timezone-aware")
    start = start.astimezone(UTC)
    remaining = duration
    day = start.astimezone(cal.tz).date() - timedelta(days=1)  # a window may begin the previous local day
    for _ in range(MAX_SEARCH_DAYS):
        for ws, we in cal.windows_utc(day):
            if we <= start:
                continue
            s = max(ws, start)
            if s + remaining <= we:
                return s + remaining
            remaining -= we - s
        day += timedelta(days=1)
    raise CalendarError(f"no service time found within {MAX_SEARCH_DAYS} days")


def service_time_between(cal: Calendar, start: datetime, end: datetime) -> timedelta:
    total = timedelta()
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    day = start.astimezone(cal.tz).date() - timedelta(days=1)
    while True:
        wins = cal.windows_utc(day)
        if wins and wins[0][0] >= end:
            break
        for ws, we in wins:
            lo, hi = max(ws, start), min(we, end)
            if hi > lo:
                total += hi - lo
        day += timedelta(days=1)
        if datetime.combine(day, time(0), cal.tz).astimezone(UTC) >= end + timedelta(days=1):
            break
    return total
