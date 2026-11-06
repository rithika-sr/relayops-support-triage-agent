# Manual review rubric

Status: **pending**. No human annotations have been recorded. Automated checks and any model judge must not be
reported as human review.

## Sample

At least 30 preselected final-test cases, stratified across the six categories and across answer, clarification,
and handoff routes, reviewed only after the configuration is frozen. If one reviewer annotates, say so; a second
reviewer on a subset is preferred.

## Claim support

For each substantive factual claim in the customer reply, read the cited source span and record one label:

| Label | Meaning |
| --- | --- |
| supported | The cited span states the claim |
| contradicted | The cited span or a current policy says otherwise |
| not_established | No cited span establishes the claim |

Report claim support precision as supported / evaluated claims, with sample and claim counts. Report unsupported
high-impact claims (entitlements, deadlines, causes, outage status) separately.

## Customer usefulness (0-2)

0 incorrect or unusable · 1 partly useful, material information missing · 2 correct and actionable.

## Engineering handoff

Score each applicable field present and accurate: component, observations separated from hypotheses, reproduction
facts, impact, related-issue handling, missing-fact disclosure. Inapplicable fields do not count.

## Annotation file

Record annotations as JSON lines in `evals/results/annotations-<reviewer>-<date>.jsonl` with
`case_id, system, claim, label, source_id, usefulness, reviewer, reviewed_at`.
