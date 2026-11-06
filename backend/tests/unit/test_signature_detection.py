"""Error codes written in free text are detected as reported observations; near-misses are not."""

from __future__ import annotations

import pytest

from relayops.domain.incidents import detect_signatures
from relayops.domain.playbooks import choose_default_playbook

KNOWN = ["EXPORT_500", "WEBHOOK_SIG_MISMATCH", "SLACK_DELIVERY_DELAY"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Exporting fails with EXPORT_500 every time.", ["EXPORT_500"]),
        ("we get an 'export 500' error on the big export", ["EXPORT_500"]),
        ("Seeing Export-500 when exporting large projects.", ["EXPORT_500"]),
        ("large CSV exports fail with export500", ["EXPORT_500"]),
        ("Attaching a PDF fails with ATTACH_CHECKSUM_FAIL.", ["ATTACH_CHECKSUM_FAIL"]),  # not in records: still a code
        ("webhook_sig_mismatch on deliveries", ["WEBHOOK_SIG_MISMATCH"]),
    ],
)
def test_detects_codes_and_loose_spellings(text, expected):
    assert detect_signatures(text, KNOWN) == expected


@pytest.mark.parametrize(
    "text",
    [
        "We export 500 rows to CSV each week; how do we schedule it?",  # spaced match without a failure word
        "Our export of 5000 rows fails.",  # different number
        "Please export 500a tasks",  # token continues
        "It's slow.",
        "Can we turn SSO_ON for everyone?",  # strict code needs a digit or 8+ characters
    ],
)
def test_near_misses_are_not_codes(text):
    assert detect_signatures(text, KNOWN) == []


def test_playbook_choice_uses_whole_words():
    body = "When I export Fleet Planning to CSV the page says EXPORT_500 and nothing downloads."
    assert choose_default_playbook(error_code="EXPORT_500", subject="Big export broken", body=body) == "bug"
    assert choose_default_playbook(error_code=None, subject="Service down", body="Everything is down.") == "incident"
