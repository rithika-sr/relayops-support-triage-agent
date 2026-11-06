# 0006: Deterministic incident grouping with review before confirmation

Status: accepted

## Context

Support needs to see when reports cluster, with correct affected-account counts, without the system declaring
outages on its own.

## Decision

Candidates group open tickets within one organization by component, normalized error signature, product version,
and a sliding time window (default 6 hours, configurable 1-72). Counts are computed from records (tickets and distinct
customer accounts). A candidate becomes an incident, or links to one, only through a staff review that pins the exact
ticket set; publishing a customer-facing summary requires an admin.

## Consequences

- Grouping is explainable and testable; embeddings are not used to merge records.
- Paraphrased reports without an error code do not group; that is a known limitation.
