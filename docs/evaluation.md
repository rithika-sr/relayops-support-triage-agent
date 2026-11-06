# Evaluation

This document describes how RelayOps is evaluated and reports only numbers that were measured. Every number below
comes from a committed report in [`evals/results/`](../evals/results/) that names its commit, dataset hashes, model
digest, and environment.

## Dataset

- **Main set:** 180 labeled synthetic cases (plus a 6-case challenge suite): six categories (how-to, known issue, new engineering handoff, clarification, feature
  request, incident) x ten root families x three paraphrases, built by
  [`evals/datasets/build_cases.py`](../evals/datasets/build_cases.py) from the structured world truth in
  `data/fixtures/world.json`. Tickets are author-written templates; no model generated, answered, or graded them.
- Splits are by root family, 4/3/3 families per category: **dev 72, validation 54, test 54** cases. Paraphrases of one
  failure never cross splits. Hashes for each split are in
  [`split_manifest.json`](../evals/datasets/split_manifest.json); the runner refuses to run if they do not match.
- The five curated category demos (current-policy SSO answer, cited webhook how-to, known EXPORT_500 link, missing
  information, new webhook handoff) are dev cases. A separate **challenge suite** of 6 cases (cross-tenant disclosure
  request, prompt injection, unverified P1 claim, security report, obsolete historical case, same-symptom different
  version) is reported apart from category scores; the disclosure trap is the sixth demo.
- Gold labels live only in `evals/`; the runner checks that no case ID appears in the runtime knowledge corpus. Each
  case uses the fixed world anchor (`2026-11-06T12:00:00Z`) as its as-of time in a dedicated evaluation database.
- **Hard slice (hard_v1):** 30 author-written cases in ten families, built by
  [`build_hard_cases.py`](../evals/datasets/build_hard_cases.py), with no structured fields: error codes only in free
  text or misspelled, version near-misses, paraphrased entitlement questions, conflicting history, uncommon errors,
  an incident without a code, ambiguity, and subtle security language. Splits by family: **dev 12, validation 9,
  test 9** ([`hard_split_manifest.json`](../evals/datasets/hard_split_manifest.json)).
- Per system, a full run plans 210 cases (180 + 30); the dev and validation splits are 147 (126 + 21). The test splits
  (63 cases per system) are **frozen and have not been run**; no configuration was selected by looking at them.
- Limitation: a small, balanced synthetic benchmark. It measures this test mix, not a real company's ticket
  distribution, and the templated tickets carry structured fields (component, version, error code) that make
  rule-based routing unusually easy.

## Systems compared

| System | Behavior |
| --- | --- |
| rules | Keyword and field rules: security language → specialist review; feature phrasing → feature request; an error code that matches a reviewed incident → incident link; an issue matching signature and version → link; any other error code → handoff; questions → answer; otherwise clarification. Lexical retrieval top 5. No model. |
| rag | One fixed retrieval stage: knowledge RRF top 5 for the ticket text, issue search on the ticket's signature and version (top 3), the incident snapshot for the component, and the same trusted account facts and entitlements; then one schema-constrained generation that returns route, links, reply, and citations. |
| agent | The product runtime on the adaptive path (`execution=agent`): trusted lookups, bounded tool use (≤4 turns, ≤6 calls), routing constraints, a customer-audience evidence view, and verification, stopped at review. |
| hybrid | The same runtime on the selective path (`execution=selective`): when a documented policy rule decides the route from records (restricted, reviewed incident, one signature+version issue, new signature, typed entitlement), that route is used with no investigation; otherwise it falls back to the adaptive path. The model still drafts the reply. |

**rules uses no generation model.** rag, agent, and hybrid use the same local model (`qwen3:4b-instruct`, digest
`0edcdef34593…`); all four use the same authorized services and world snapshot. Hybrid's gains on decided cases come
from deterministic rules, not from the model investigating better.

## Metrics

Route accuracy (with per-route counts), evidence recall@k on cases with required evidence (k = what each system
retrieved: 5 for rules and RAG, every passage the agent's tools returned), provenance validity (cited IDs that exist,
were retrieved, and are customer-visible, over all cited IDs), issue-link accuracy on known-issue and feature cases,
forbidden-claim cases (SSO/SCIM entitlement misstatements, "fixed", asserted root cause, confirmed outage, cross-tenant
names, wrong version link), latency p50/p95 per case including all orchestration and verification, and model and tool
call counts. Failed and errored cases are kept in every denominator.

Each report also records macro F1, issue-link precision and recall, a clarification proxy, and handoff field
completeness. Intervals below are Wilson 95% intervals on route accuracy; the samples are small and correlated within
families, so treat them as rough.

Not measured: **human claim-support review** (no human labels exist; status pending), and the final test splits.

## Results

### Run 1: broad comparison at `9ba4ddb` (exploratory for this release)

Report [`full-20261106T160439`](../evals/results/full-20261106T160439.md); 588 of 840 planned pairs (4 systems ×
147 dev+validation cases; the 252 unrun pairs are the frozen test splits). Provenance: launched in the main checkout
right after committing `9ba4ddb`. 58 hybrid rows recorded during a Docker/Postgres outage were removed and re-run with
`--resume` from a clean worktree at the same commit; the report metadata records `repository_commit=9ba4ddb…`.
The runtime fixes below were made *after* this run, so it does not describe the final release.

| System | Slice | Route correct | 95% interval | Latency p50 / p95 | Model calls (mean) |
| --- | --- | --- | --- | --- | --- |
| rules | main | 122/126 (0.97) | 0.92–0.99 | 0.0 / 0.0 s | 0 |
| rules | hard | 6/21 (0.29) | 0.14–0.50 | 0.0 / 0.0 s | 0 |
| rag | main | 74/126 (0.59) | 0.50–0.67 | 4.6 / 9.3 s | 1.0 |
| rag | hard | 9/21 (0.43) | 0.24–0.63 | 5.8 / 7.3 s | 1.0 |
| agent | main | 70/126 (0.56) | 0.47–0.64 | 24.8 / 31.7 s | 6.4 |
| agent | hard | 5/21 (0.24) | 0.11–0.45 | 27.3 / 32.8 s | 6.2 |
| hybrid | main | 93/126 (0.74) | 0.66–0.81 | 19.1 / 36.8 s | 4.3 |
| hybrid | hard | 5/21 (0.24) | 0.11–0.45 | 28.3 / 34.7 s | 5.6 |

| Slice / category | rules | rag | agent | hybrid |
| --- | --- | --- | --- | --- |
| main / how_to | 19/21 | 18/21 | 18/21 | 18/21 |
| main / known_issue | 21/21 | 21/21 | 18/21 | 18/21 |
| main / new_handoff | 21/21 | 2/21 | 1/21 | 21/21 |
| main / clarification | 20/21 | 11/21 | 12/21 | 12/21 |
| main / feature_request | 20/21 | 9/21 | 21/21 | 21/21 |
| main / incident | 21/21 | 13/21 | 0/21 | 3/21 |
| hard / how_to | 6/6 | 4/6 | 5/6 | 5/6 |
| hard / known_issue | 0/6 | 5/6 | 0/6 | 0/6 |
| hard / new_handoff | 0/6 | 0/6 | 0/6 | 0/6 |
| hard / incident | 0/3 | 0/3 | 0/3 | 0/3 |

Other measures (all 147 cases per system): forbidden-claim cases rules 0, rag **8**, agent 0, hybrid 0; provenance
validity of cited sources rag 295/374 (0.79), agent 357/357, hybrid 353/353 (rules cites nothing). Challenge suite:
6 cases, no unsafe draft passed verification.

### What went wrong in run 1, and why

Traced from the recorded run events in the evaluation database, not inferred from scores:

1. **Adaptive agent: 0/21 incidents and 1/21 new handoffs (main).** In traced runs the model's own rationale said no
   known issue matched, then it chose clarification. The propose prompt said only when to ask ("if required facts are
   missing, choose clarification") and never when to hand off or link an incident; the incident playbook requires
   `first_seen`, which customers rarely state. The precheck had already found the reviewed incident or the absence of
   any issue, but the adaptive path did not show those lookups to the model, and the model seldom called the incident
   tool itself. *Fix (`b7d9c5e`):* positive route rules in the prompt, the trusted lookup summary in the code-computed
   signals, and record-backed issues/incidents registered as evidence on both paths.
2. **Hard slice, every system.** Error codes written only in free text or misspelled ("export 500", "Export-500")
   were never extracted, so no lookup ran; and the default playbook used substring matching, so "nothing
   **down**loads" chose the incident playbook and "Export_500 again" chose how-to, which cannot link issues.
   *Fix (`165aef1`):* detect strict codes and the organization's known signatures in customer text (recorded as
   reported, never verified; "we export 500 rows" is not a code) and whole-word playbook matching. Phrases from the
   frozen test families were deliberately not added.
3. **Hybrid: 3/21 incidents (main).** The precheck looked incidents up through a browsing snapshot capped at the five
   most recent; with ten active incidents in the world, older ones with the reported signature were cut off and the
   policy routed a new handoff. *Fix (`5d5a349`):* exact signature lookup with no recency limit.
4. **rules on the hard slice (6/21)** reflects the baseline's design: it routes on structured fields, which the hard
   slice removes. The baseline was not changed.
5. **rag's forbidden claims (8)** and lower provenance come from a single generation without verification; rag was
   not changed.

Gold labels were not edited, no case IDs are referenced in code, and the rules and rag baselines are unchanged.

### Run 2: agent after the first fixes, at `40320eb` (intermediate)

Rows: [`full-r2-40320eb-rows.jsonl`](../evals/results/full-r2-40320eb-rows.jsonl) (rules and agent, 147 dev+validation
cases each, from a clean worktree at `40320eb` with its own database). The hybrid pass was stopped unfinished once
the regressions below were found and fixed, so no hybrid numbers are reported for this revision. Latency for the first
~25 agent cases is inflated by screenshot runs sharing the machine.

| System | Slice | Route correct | 95% interval | Latency p50 / p95 |
| --- | --- | --- | --- | --- |
| rules | main | 122/126 (0.97) | 0.92–0.99 | 0.0 / 0.0 s |
| rules | hard | 6/21 (0.29) | 0.14–0.50 | 0.0 / 0.0 s |
| agent | main | 78/126 (0.62) | 0.53–0.70 | 26.7 / 38.7 s |
| agent | hard | 14/21 (0.67) | 0.45–0.83 | 28.3 / 36.4 s |

Against run 1, the agent improved on new handoffs (main 1 → 13 of 21; hard 0 → 6 of 6), hard how-to (5 → 6), hard
known issues (0 → 2), and incidents (0 → 4), and **regressed on clarification (12 → 6 of 21)** and how-to (18 → 16).
Traced causes, both fixed before run 3:

6. **Vague tickets sent to the restricted queue.** When the model picked a route the playbook does not allow, code
   fell back to specialist review, which restricts the ticket (the security queue). Six vague tickets landed there.
   The run 1 prompt change also told the model that missing facts alone were no reason to ask. *Fix (`2794ba1`):*
   a disallowed route falls back to clarification when the playbook allows it; the clarification rule is stated
   positively.
7. **Incidents still missed (4/21).** The bug playbook, which error-code tickets get, did not allow `incident_link`,
   so the policy rule could not apply and the model's choice was downgraded. *Fix (`66c4f75`):* the default bug
   playbook allows incident links. The same commit provisions default playbooks at registration; before it, a new
   operational organization had none and could not start an investigation.

<!-- RUN3 -->


## Claim verification calibration

Reports [`claims-20261106T181122`](../evals/results/claims-20261106T181122.md) (local verifier) and
[`claims-20261106T173843-off`](../evals/results/claims-20261106T173843-off.md) (typed rules only). 52 synthetic items
in two splits; labels were drafted with AI assistance, **not** independent human annotation.

| Split | Items | Typed rules decided | Typed correct | Model decided | Model correct | Contradictions caught | False supported | Abstained |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev (used to build typed rules) | 28 | 8 | 8 | 20 | 19 | 9/9 | 0 | 0 |
| validation (held out) | 24 | 6 | 5 | 18 | 17 | 5/6 | 1 | 0 |

The held-out false "supported" is a typed number check: the sentence's number matches a cited value that belongs to a
different plan. Typed rules cover few sentences (14 of 52); the rest depend on the local model, whose verdicts are an
estimate. The worked example shows a model false positive on real output (an error code described with another code's
meaning). These measurements are not human claim review, which remains **pending**.

## Reproducing

```bash
make eval-offline                                   # seconds; fails on gate violations
make eval-full                                      # four systems, both datasets, dev+validation; hours; resumable
uv --directory backend run python ../evals/runners/claims_calibration.py
python3 evals/runners/analyze.py evals/results/full-<tag>.json
```

Runs are resumable (`--resume <tag>`), and `RELAYOPS_EVAL_DB_NAME` gives a run its own database. Add `--include-test`
only for a final, frozen configuration, and record that the test split was consumed.
