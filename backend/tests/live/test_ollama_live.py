"""Real local-model checks. Run with `make test-live`; these never use the fixture provider.

They fail (not skip) when Ollama or the configured models are missing, so a missing dependency cannot pass.
"""

from __future__ import annotations

import pytest

from relayops.agents import llm
from relayops.core.config import get_settings
from tests.agent_helpers import CUSTOMER, SUPPORT, client, drain, export_ticket, seeded

pytestmark = pytest.mark.live


@pytest.fixture
def ollama():
    provider = llm.OllamaProvider(get_settings().model_copy(update={"llm_provider": "ollama"}))
    llm.set_provider(provider)
    health = provider.health()
    assert health["reachable"], f"Ollama unreachable: {health}"
    assert health["chat_model_present"], f"{provider.chat_model} not installed"
    assert health["embed_model_present"], f"{provider.embed_model} not installed"
    return provider


def test_embedding_dimension_matches_index(ollama):
    [vec] = ollama.embed(["exports fail with EXPORT_500"])
    assert len(vec) == get_settings().embed_dim == 768


def test_structured_output_is_valid_json(ollama):
    res = ollama.chat_json(purpose="probe", system="Return JSON only.", user='Return {"ok": true}.',
                           schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                           timeout=120, max_tokens=20)
    assert res.parsed == {"ok": True}
    assert ollama.model_digest()


def test_real_tool_driven_run_reaches_review(ollama, db, tmp_path):
    creds = seeded(db, tmp_path)
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"}).json()["id"]
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert d["run"]["model_provider"] == "ollama"
    assert d["run"]["status"] == "awaiting_review", d["run"]
    assert d["run"]["usage"]["tool_calls"] >= 1
    assert any(e["kind"] == "model_call" and e["payload"]["provider"] == "ollama" for e in d["events"])
    prop = d["proposals"][0]
    assert prop["route"] in {"link_existing_issue", "new_engineering_handoff", "clarification", "specialist_review",
                             "answer_draft"}
