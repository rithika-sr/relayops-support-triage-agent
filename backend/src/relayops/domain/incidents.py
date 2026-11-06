"""Deterministic incident-constellation grouping.

Tickets group when component, normalized error signature, and affected version match and reports fall
inside a sliding time window. A candidate is not a confirmed incident: confirmation requires review.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

_LONG_NUMBER = re.compile(r"(?<![A-Z0-9])\d{4,}(?![A-Z0-9])")
_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.I)


def normalize_signature(raw: str | None) -> str | None:
    if not raw:
        return None
    sig = raw.strip().upper()
    sig = _HEX.sub("<ID>", sig)
    sig = re.sub(r"[\s\-]+", "_", sig)
    return _LONG_NUMBER.sub("<N>", sig)


STRICT_CODE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Za-z0-9_])")
_FAILURE_WORDS = re.compile(r"\b(error|errors|fail\w*|broken|crash\w*|says|shows|returns?|gives?|got|get)\b", re.I)


def detect_signatures(text: str, known: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Error signatures the customer wrote in free text, as reported observations (never verified facts).

    Two sources: strict UPPER_SNAKE codes anywhere (ATTACH_CHECKSUM_FAIL), and the organization's known signatures
    written loosely (export 500, Export-500, export500). A loose match separated by a space counts only in a
    sentence that also describes a failure, so "we export 500 rows" is not an error code.
    """
    found: list[str] = []
    for m in STRICT_CODE.finditer(text):
        if any(ch.isdigit() for ch in m.group(1)) or len(m.group(1)) >= 8:
            found.append(m.group(1))
    sentences = re.split(r"(?<=[.!?\n])\s+", text)
    for sig in known:
        parts = [p for p in re.split(r"[_\s\-]+", sig) if p]
        if len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9]+", p) for p in parts):
            continue
        tight = re.compile(r"(?<![A-Za-z0-9])" + r"[_\-]?".join(map(re.escape, parts)) + r"(?![A-Za-z0-9])", re.I)
        spaced = re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(map(re.escape, parts)) + r"(?![A-Za-z0-9])", re.I)
        for s in sentences:
            if tight.search(s) or (spaced.search(s) and _FAILURE_WORDS.search(s)):
                found.append(sig)
                break
    out: list[str] = []
    for f in found:
        n = normalize_signature(f)
        if n and n not in out:
            out.append(n)
    return out


@dataclass(frozen=True)
class SignalTicket:
    ticket_id: str
    customer_account_id: str
    component: str | None
    error_code: str | None
    product_version: str | None
    created_at: datetime


@dataclass
class Constellation:
    key: str
    component: str
    signature: str
    product_version: str
    ticket_ids: list[str] = field(default_factory=list)
    account_ids: set[str] = field(default_factory=set)
    first_reported_at: datetime | None = None
    last_reported_at: datetime | None = None

    @property
    def distinct_accounts(self) -> int:
        return len(self.account_ids)


def group_signals(
    tickets: list[SignalTicket], *, window: timedelta = timedelta(hours=6), min_tickets: int = 2
) -> list[Constellation]:
    buckets: dict[tuple[str, str, str], list[SignalTicket]] = {}
    for t in tickets:
        sig = normalize_signature(t.error_code)
        if not (t.component and sig and t.product_version):
            continue
        buckets.setdefault((t.component, sig, t.product_version), []).append(t)

    out: list[Constellation] = []
    for (component, sig, version), items in buckets.items():
        items.sort(key=lambda t: (t.created_at, t.ticket_id))
        current: list[SignalTicket] = []
        for t in items:
            if current and t.created_at - current[-1].created_at > window:
                out.extend(_emit(component, sig, version, current, min_tickets))
                current = []
            current.append(t)
        out.extend(_emit(component, sig, version, current, min_tickets))
    out.sort(key=lambda c: (-c.distinct_accounts, -(len(c.ticket_ids)), c.key))
    return out


def _emit(component: str, sig: str, version: str, items: list[SignalTicket], min_tickets: int) -> list[Constellation]:
    if len(items) < min_tickets:
        return []
    ids = sorted(t.ticket_id for t in items)
    key = hashlib.sha256("|".join([component, sig, version, *ids]).encode()).hexdigest()[:16]
    return [
        Constellation(
            key=key,
            component=component,
            signature=sig,
            product_version=version,
            ticket_ids=ids,
            account_ids={t.customer_account_id for t in items},
            first_reported_at=items[0].created_at,
            last_reported_at=items[-1].created_at,
        )
    ]


def candidate_window(c: Constellation, padding: timedelta = timedelta(hours=0)) -> tuple[datetime, datetime]:
    assert c.first_reported_at and c.last_reported_at
    return c.first_reported_at - padding, c.last_reported_at + padding
