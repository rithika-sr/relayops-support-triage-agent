# 0005: A labeled fixture provider for offline tests, never a silent fallback

Status: accepted

## Context

Most behavior (scope, budgets, review, recovery) must be tested deterministically in CI without a model. Live model
quality must not be inferred from those tests.

## Decision

`FixtureProvider` returns scripted JSON and hash-based vectors tagged `fixture-hash-v1`. It is used only when
`RELAYOPS_LLM_PROVIDER=fixture`. Runs record `model_provider=fixture` and the UI flags them. Dense retrieval only
uses vectors whose model matches the configured embedding model, so fixture vectors never mix with real ones.
There is no automatic fallback from Ollama to fixtures: an unavailable model fails the run visibly.

## Consequences

- CI runs the full runtime and a browser journey without credentials or GPUs.
- `make test-live` and the live evaluation profiles are the only sources of model-quality claims.
