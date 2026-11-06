# 0011: Claim-level support with typed checks and a pinned local verifier

Status: accepted

## Context

Verification reported lexical overlap between the reply and cited sources, which says little about whether a claim
is supported. A paid hosted model was out of scope, and a model judgment must not be presented as proof.

## Decision

Split replies into sentences and classify them (social, request, hypothesis, procedural, factual). Social text and
questions are never "unsupported". Typed rules decide entitlement statements (entity and negation against the plan
record) and numbers with units (durations compare across units). Remaining substantive claims go to a configurable
local verifier that sees only the cited, customer-visible passages and returns supported, contradicted,
insufficient evidence, or unavailable. The verifier's model and digest are stored with each verification.

- A contradicted claim fails verification.
- Uncertain substantive claims require an explicit acknowledgment at approval, which is audited.
- Reviewer edits get typed checks only; the semantic verifier is marked not run for human text.
- Human labels are separate, immutable records bound to the claim text by hash; agreement statistics stay
  "pending" until real labels exist.

## Consequences

- A 28-item author-labeled calibration set measures the typed rules and the verifier. It was used while building
  the typed rules, so it is a development set.
- The verifier adds model calls per draft (bounded by the number of substantive sentences).
