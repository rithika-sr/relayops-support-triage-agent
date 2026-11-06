"""Service calendars: windows, holidays, and DST in IANA zones."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from relayops.domain.calendars import Calendar, CalendarError, add_service_time, service_time_between, validate

WEEKDAYS = {d: [("09:00", "17:00")] for d in ("mon", "tue", "wed", "thu", "fri")}


def cal(tz="America/New_York", weekly=None, holidays=()):
    return Calendar("default", 1, tz, weekly or WEEKDAYS, frozenset(holidays))


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_inside_and_across_windows():
    c = cal()
    # Mon 2026-11-02 10:00 EST = 15:00 UTC; +4h stays the same day.
    assert add_service_time(c, utc(2026, 11, 2, 15), timedelta(hours=4)) == utc(2026, 11, 2, 19)
    # +10h: 7h Monday (10-17), 3h Tuesday (9-12 EST = 14-17 UTC).
    assert add_service_time(c, utc(2026, 11, 2, 15), timedelta(hours=10)) == utc(2026, 11, 3, 17)


def test_weekend_and_holiday_are_skipped():
    c = cal(holidays=[date(2026, 11, 26)])  # Thanksgiving
    # Fri 16:00 EST + 2h -> 1h Friday, 1h Monday.
    assert add_service_time(c, utc(2026, 11, 6, 21), timedelta(hours=2)) == utc(2026, 11, 9, 15)
    # Wed 16:00 EST + 2h -> 1h Wed, Thu is a holiday, 1h Fri.
    assert add_service_time(c, utc(2026, 11, 25, 21), timedelta(hours=2)) == utc(2026, 11, 27, 15)


def test_fall_back_keeps_local_window_and_moves_utc():
    c = cal()
    # DST ends Sun 2026-11-01 in New York. Fri Oct 30 16:00 EDT (20:00 UTC) + 2h -> Mon 10:00 EST = 15:00 UTC.
    assert add_service_time(c, utc(2026, 10, 30, 20), timedelta(hours=2)) == utc(2026, 11, 2, 15)


def test_spring_forward_window_spanning_the_gap_is_an_hour_shorter():
    c = cal(weekly={"sun": [("01:00", "05:00")]})
    # DST starts Sun 2026-03-08 at 02:00 in New York: 01:00-05:00 local is 3 real hours.
    start = utc(2026, 3, 8, 6)  # 01:00 EST
    assert add_service_time(c, start, timedelta(hours=3)) == utc(2026, 3, 8, 9)  # 05:00 EDT
    assert add_service_time(c, start, timedelta(hours=4)) == utc(2026, 3, 15, 6)  # next Sunday 01:00 EDT +1h


def test_fall_back_window_spanning_the_repeat_is_an_hour_longer():
    c = cal(weekly={"sun": [("00:00", "03:00")]})
    start = utc(2026, 11, 1, 4)  # 00:00 EDT
    assert service_time_between(c, start, utc(2026, 11, 1, 12)) == timedelta(hours=4)


def test_other_zones_and_midnight_windows():
    tokyo = cal("Asia/Tokyo", weekly={"mon": [("00:00", "24:00")]})
    assert add_service_time(tokyo, utc(2026, 11, 1, 15), timedelta(hours=24)) == utc(2026, 11, 2, 15)
    london = cal("Europe/London")
    # UK DST ended Oct 25; Mon Oct 26 09:00 GMT = 09:00 UTC.
    assert add_service_time(london, utc(2026, 10, 26, 8), timedelta(minutes=30)) == utc(2026, 10, 26, 9, 30)


@pytest.mark.parametrize(
    ("tz", "weekly", "holidays", "msg"),
    [
        ("Mars/Olympus", WEEKDAYS, [], "unknown IANA"),
        ("UTC", {"funday": [("09:00", "10:00")]}, [], "unknown day"),
        ("UTC", {"mon": [("17:00", "09:00")]}, [], "must end after"),
        ("UTC", {"mon": [("09:00", "12:00"), ("11:00", "13:00")]}, [], "overlap"),
        ("UTC", {"mon": [("9am", "5pm")]}, [], "HH:MM"),
        ("UTC", {}, [], "at least one"),
        ("UTC", WEEKDAYS, ["26/11/2026"], "YYYY-MM-DD"),
    ],
)
def test_validation(tz, weekly, holidays, msg):
    with pytest.raises(CalendarError, match=msg):
        validate(tz, {k: [list(w) for w in v] for k, v in weekly.items()}, holidays)


def test_naive_start_is_rejected():
    with pytest.raises(CalendarError):
        add_service_time(cal(), datetime(2026, 11, 2, 10), timedelta(hours=1))
