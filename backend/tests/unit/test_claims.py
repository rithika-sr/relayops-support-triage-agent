"""Claim classification, typed checks, and the semantic verifier contract (offline)."""

from __future__ import annotations

import pytest

from relayops.agents import claims
from relayops.agents.llm import FixtureProvider
from relayops.domain.policies import entitlements_for

BUSINESS = entitlements_for("business")
SPAN = {"E1": "Business plans can export up to 25,000 rows. Background exports finish within 2 hours."}


@pytest.mark.parametrize(
    ("sentence", "kind"),
    [
        ("Thanks for reaching out.", "social"),
        ("Could you share the time it started?", "request"),
        ("Please send a screenshot of the error.", "request"),
        ("This may be related to the 2.5 upgrade.", "hypothesis"),
        ("Open Settings and choose Export.", "procedural"),
        ("Exports over 25,000 rows are split into parts.", "factual"),
    ],
)
def test_classify(sentence, kind):
    assert claims.classify(sentence) == kind


def test_social_and_requests_are_never_unsupported():
    out = claims.check_reply(
        "Thanks for your patience. Could you tell us which board?", entitlements=BUSINESS, spans={}, provider=None
    )
    assert [c.verdict for c in out] == ["not_a_claim", "not_a_claim"]


@pytest.mark.parametrize(
    ("sentence", "verdict"),
    [
        ("SSO is included in your Business plan.", "contradicted"),
        ("SSO is not included in your Business plan.", "supported"),  # negation flips polarity
        ("Single sign-on is available on Business.", "contradicted"),  # paraphrased entity
        ("You cannot enable SSO on Business.", "supported"),
        ("Business doesn't include SSO.", "supported"),
    ],
)
def test_entitlement_entity_and_polarity(sentence, verdict):
    c = claims.typed_check(sentence, entitlements=BUSINESS, spans={})
    assert c is not None and c.method == "typed_entitlement" and c.verdict == verdict


def test_numbers_need_the_same_unit_and_value():
    assert claims.typed_check("You can export 25,000 rows.", entitlements={}, spans=SPAN).verdict == "supported"
    conflict = claims.typed_check("You can export 50,000 rows.", entitlements={}, spans=SPAN)
    assert conflict.verdict == "contradicted" and conflict.evidence_ids == ["E1"]
    # Same number, different unit: the span says 2 hours, not 2 days; durations compare across units.
    assert claims.typed_check("Exports finish within 2 days.", entitlements={}, spans=SPAN).verdict == "contradicted"
    assert claims.typed_check("Exports finish within 120 minutes.", entitlements={}, spans=SPAN).verdict == "supported"
    assert claims.typed_check("Exports finish within two hours.", entitlements={}, spans=SPAN).verdict == "supported"
    # A unit the cited span never mentions is not evidence either way.
    assert claims.typed_check("Retries happen 3 times.", entitlements={}, spans=SPAN).verdict == "insufficient_evidence"
    assert claims.typed_check("It finishes in 2 h.", entitlements={}, spans=SPAN).verdict == "supported"  # alias


def test_valid_but_irrelevant_citation_is_not_support():
    def script(purpose, user):
        assert purpose == "claim_verifier" and "<passage" in user
        return {"verdict": "insufficient_evidence", "evidence_ids": ["E1"], "reason": "passage is about exports"}

    out = claims.check_reply(
        "Slack notifications are delivered instantly.", entitlements={}, spans=SPAN, provider=FixtureProvider(script)
    )
    assert (out[0].verdict, out[0].method) == ("insufficient_evidence", "semantic_model")


def test_verifier_cannot_cite_spans_it_was_not_given():
    out = claims.semantic_check(
        FixtureProvider(lambda p, u: {"verdict": "supported", "evidence_ids": ["E1", "E7"]}),
        "Background exports finish within two hours overall.",
        SPAN,
        timeout=5,
    )
    assert out.verdict == "supported" and out.evidence_ids == ["E1"]


@pytest.mark.parametrize("bad", [None, "not json", {"verdict": "probably"}])
def test_verifier_failures_are_unavailable_not_supported(bad):
    def script(purpose, user):
        if bad is None:
            raise TimeoutError
        return bad

    out = claims.semantic_check(FixtureProvider(script), "Exports finish quickly.", SPAN, timeout=5)
    assert out.verdict == "unavailable"


def test_no_cited_spans_means_insufficient_without_a_model_call():
    calls = []
    out = claims.semantic_check(FixtureProvider(lambda p, u: calls.append(p)), "Exports work.", {}, timeout=5)
    assert out.verdict == "insufficient_evidence" and calls == []


def test_hedged_sentences_are_still_checked_when_sources_are_cited():
    seen = []

    def script(purpose, user):
        seen.append(purpose)
        return {"verdict": "contradicted", "evidence_ids": ["E1"]}

    out = claims.check_reply(
        "Exports may take a day or more.", entitlements={}, spans=SPAN, provider=FixtureProvider(script)
    )
    assert out[0].kind == "hypothesis" and out[0].verdict == "contradicted" and seen == ["claim_verifier"]
