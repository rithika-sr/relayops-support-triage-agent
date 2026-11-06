"""Injectable UTC clock so deadlines and evaluations can run against a fixed as-of time."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def utcnow() -> datetime:
    return _now()


@contextmanager
def frozen_clock(at: datetime) -> Iterator[None]:
    global _now
    if at.tzinfo is None:
        raise ValueError("frozen clock requires an aware UTC datetime")
    previous = _now
    _now = lambda: at  # noqa: E731
    try:
        yield
    finally:
        _now = previous
