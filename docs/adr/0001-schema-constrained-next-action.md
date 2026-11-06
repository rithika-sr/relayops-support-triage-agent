# 0001: Schema-constrained next actions instead of native tool calling

Status: accepted

## Context

The investigator runs on a 4B local model through Ollama. It must choose read tools adaptively, but the runtime has
to enforce budgets, scope, and argument validity, and must record a short purpose for each step.

## Decision

Each investigation turn asks for one JSON object (`purpose`, `action`, `tool_calls[≤2]`) constrained by a JSON
schema with bounded string lengths and array sizes, validated with pydantic, and dispatched by code. Every model
step gets at most one repair attempt per run.

## Consequences

- Dispatch, budgets, duplicate-call detection, and argument validation are ordinary code paths with tests.
- Bounded `maxLength`/`maxItems` were necessary: without them the 4B model sometimes ran away inside one string and
  produced truncated JSON.
- Native tool calling may be revisited when a model is measured to use it reliably; the dispatcher would not change.
