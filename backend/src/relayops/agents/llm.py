"""Model adapters.

`OllamaProvider` performs real local inference and embeddings. `FixtureProvider` is a deterministic,
clearly labeled stand-in for offline tests only; its vectors are tagged `fixture-hash-v1` and are never
accepted by the live retrieval path (see retrieval.embedding_model_guard).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from relayops.core.config import Settings, get_settings

FIXTURE_EMBED_MODEL = "fixture-hash-v1"


class ModelUnavailable(Exception):
    """Ollama is not reachable, the model is missing, or inference exceeded its deadline."""


@dataclass
class ModelResult:
    content: str
    parsed: dict[str, Any] | None
    parse_error: str | None
    duration_ms: int
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str
    chat_model: str
    embed_model: str

    def chat_json(
        self, *, purpose: str, system: str, user: str, schema: dict[str, Any], timeout: float, max_tokens: int
    ) -> ModelResult: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def model_digest(self) -> str | None: ...


def _parse(content: str) -> tuple[dict[str, Any] | None, str | None]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc.msg} at char {exc.pos}"
    if not isinstance(value, dict):
        return None, "top-level JSON value must be an object"
    return value, None


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.s = settings or get_settings()
        self.chat_model = self.s.chat_model
        self.embed_model = self.s.embed_model
        self._client = client or httpx.Client(base_url=self.s.ollama_base_url)
        self._digest: str | None = None

    def chat_json(
        self, *, purpose: str, system: str, user: str, schema: dict[str, Any], timeout: float, max_tokens: int
    ) -> ModelResult:
        body = {
            "model": self.chat_model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0.1, "num_ctx": self.s.num_ctx, "num_predict": max_tokens, "seed": 7},
            "keep_alive": "15m",
        }
        started = time.monotonic()
        try:
            r = self._client.post("/api/chat", json=body, timeout=max(1.0, timeout))
        except httpx.TimeoutException as exc:
            raise ModelUnavailable(f"inference exceeded {timeout:.0f}s deadline") from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"Ollama unreachable: {exc.__class__.__name__}") from exc
        if r.status_code == 404:
            raise ModelUnavailable(f"model {self.chat_model} is not installed in Ollama")
        if r.status_code >= 400:
            raise ModelUnavailable(f"Ollama error {r.status_code}: {r.text[:200]}")
        data = r.json()
        content = data.get("message", {}).get("content", "")
        parsed, err = _parse(content)
        return ModelResult(
            content=content,
            parsed=parsed,
            parse_error=err,
            duration_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            meta={"purpose": purpose, "done_reason": data.get("done_reason")},
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        clipped = [t[: self.s.embed_max_chars] for t in texts]
        try:
            r = self._client.post(
                "/api/embed", json={"model": self.embed_model, "input": clipped, "truncate": True}, timeout=120
            )
        except httpx.HTTPError as exc:
            raise ModelUnavailable(f"Ollama embeddings unreachable: {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            raise ModelUnavailable(f"embedding model {self.embed_model} unavailable: {r.text[:200]}")
        vectors = r.json().get("embeddings") or []
        if len(vectors) != len(texts):
            raise ModelUnavailable("embedding response size mismatch")
        dim = len(vectors[0])
        if dim != self.s.embed_dim:
            raise ModelUnavailable(
                f"embedding dimension {dim} from {self.embed_model} does not match index dimension {self.s.embed_dim}"
            )
        return [list(map(float, v)) for v in vectors]

    def model_digest(self) -> str | None:
        if self._digest is None:
            try:
                tags = self._client.get("/api/tags", timeout=5).json().get("models", [])
            except httpx.HTTPError:
                return None
            for m in tags:
                if m.get("name") == self.chat_model or m.get("model") == self.chat_model:
                    self._digest = m.get("digest")
        return self._digest

    def health(self) -> dict[str, Any]:
        try:
            tags = self._client.get("/api/tags", timeout=3).json().get("models", [])
        except httpx.HTTPError as exc:
            return {"reachable": False, "error": exc.__class__.__name__}
        names = {m.get("name") for m in tags} | {m.get("model") for m in tags}
        embed_names = {self.embed_model, f"{self.embed_model}:latest"}
        return {
            "reachable": True,
            "chat_model": self.chat_model,
            "chat_model_present": self.chat_model in names,
            "embed_model": self.embed_model,
            "embed_model_present": bool(names & embed_names),
            "installed": sorted(n for n in names if n),
        }


Script = Callable[[str, str], dict[str, Any] | str]


class FixtureProvider:
    """Deterministic scripted provider for offline tests. Never used unless explicitly configured."""

    name = "fixture"
    chat_model = "fixture-scripted"
    embed_model = FIXTURE_EMBED_MODEL

    def __init__(self, script: Script | None = None, dim: int = 768) -> None:
        self.script = script
        self.dim = dim
        self.calls: list[dict[str, Any]] = []

    def chat_json(
        self, *, purpose: str, system: str, user: str, schema: dict[str, Any], timeout: float, max_tokens: int
    ) -> ModelResult:
        self.calls.append({"purpose": purpose, "user": user})
        if self.script is None:
            raise ModelUnavailable("fixture provider has no script for this test")
        out = self.script(purpose, user)
        content = out if isinstance(out, str) else json.dumps(out)
        parsed, err = _parse(content)
        return ModelResult(content=content, parsed=parsed, parse_error=err, duration_ms=0, meta={"purpose": purpose})

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in re.findall(r"[a-z0-9_]+", t.lower()):
                h = int(hashlib.md5(tok.encode(), usedforsecurity=False).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 12) & 1 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

    def model_digest(self) -> str | None:
        return None


_provider: Provider | None = None


def get_provider() -> Provider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.llm_provider == "fixture":
            from relayops.agents.fixture_scripts import SCRIPTS

            _provider = FixtureProvider(SCRIPTS.get(s.fixture_script))
        else:
            _provider = OllamaProvider(s)
    return _provider


def set_provider(provider: Provider | None) -> None:
    """Test hook. Production code reads the provider from configuration."""
    global _provider
    _provider = provider
