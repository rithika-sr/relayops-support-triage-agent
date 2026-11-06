# 0010: A selective, policy-first execution path beside the adaptive agent

Status: accepted

## Context

The live smoke run showed the adaptive agent hedging on cases the records already decide: a known issue matching
signature and version, a reviewed incident with the same signature, or a plan entitlement question. The rules
baseline, which reads the same records, routed those correctly with no model.

## Decision

Add a `precheck` graph node that runs trusted lookups (known issues for the reported signature and version, reviewed
incidents, this account's error aggregates, typed entitlements) and applies ordered, documented rules
(`agents/policy.py`): restricted, reviewed incident, exactly one known issue, new signature, typed entitlement.
When a rule decides, the selective path (`execution = selective`) uses that route and skips adaptive
investigation; the model still writes the reply, which is verified as usual. When no rule decides, it falls back to
the adaptive investigator. Customer-entered fields are recorded as reported, with corroboration tracked separately.

## Consequences

- The evaluation compares four systems; `hybrid` is this path, and the three earlier systems are unchanged.
- Rules can be wrong in the same way for every ticket; negative near-match tests (same signature on another
  version, normalized signatures) guard the obvious cases.
- Repeated identical tool calls no longer consume budget; two repeats end investigation with `no_new_information`.
