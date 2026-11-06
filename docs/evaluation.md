# Evaluation

This document describes how RelayOps is evaluated and reports only numbers that were measured. Every number below
comes from a committed report in [`evals/results/`](../evals/results/) that names its commit, dataset hashes, model
digest, and environment.

## Dataset

- 180 labeled synthetic cases: six categories (how-to, known issue, new engineering handoff, clarification, feature
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
- Limitation: a small, balanced synthetic benchmark. It measures this test mix, not a real company's ticket
  distribution, and the templated tickets carry structured fields (component, version, error code) that make
  rule-based routing unusually easy.

## Systems compared

| System | Behavior |
| --- | --- |
| rules | Keyword and field rules: security language → specialist review; feature phrasing → feature request; an error code that matches a reviewed incident → incident link; an issue matching signature and version → link; any other error code → handoff; questions → answer; otherwise clarification. Lexical retrieval top 5. No model. |
| rag | One fixed retrieval stage: knowledge RRF top 5 for the ticket text, issue search on the ticket's signature and version (top 3), the incident snapshot for the component, and the same trusted account facts and entitlements; then one schema-constrained generation that returns route, links, reply, and citations. |
| agent | The product runtime: bounded adaptive tool use (≤4 turns, ≤6 calls), routing constraints, a customer-audience evidence view, and deterministic verification, stopped at review. |

All three use the same model (`qwen3:4b-instruct`), the same authorized services, and the same world snapshot.

## Metrics

Route accuracy (with per-route counts), evidence recall@k on cases with required evidence (k = what each system
retrieved: 5 for rules and RAG, every passage the agent's tools returned), provenance validity (cited IDs that exist,
were retrieved, and are customer-visible, over all cited IDs), issue-link accuracy on known-issue and feature cases,
forbidden-claim cases (SSO/SCIM entitlement misstatements, "fixed", asserted root cause, confirmed outage, cross-tenant
names, wrong version link), latency p50/p95 per case including all orchestration and verification, and model and tool
call counts. Failed and errored cases are kept in every denominator.

Not yet measured: claim-support precision (requires the human review in
[`evals/rubrics/manual_review.md`](../evals/rubrics/manual_review.md); status **pending**), intent macro F1,
clarification usefulness, handoff completeness, and the final test split.

## Results

### Offline profile (deterministic, gated in CI)

Report: [`offline-20261106T142707`](../evals/results/offline-20261106T142707.md), commit `24c865b`, fixture provider.

| System | Cases | Route accuracy | Evidence recall@k | Issue-link accuracy | Forbidden-claim cases |
| --- | --- | --- | --- | --- | --- |
| rules | 126 (dev + validation) | 0.97 (122/126) | 0.93 (28/30) | 0.97 (29/30) | 0 |

Challenge suite through the full runtime with an adversarial fixture model that injects an out-of-scope
`organization_id`, searches for other tenants' records, cites a nonexistent source, and writes other customers' names,
"confirmed outage", and an SSO entitlement claim into the reply: **6 cases, 3 drafts contained violations, 0 unsafe
drafts passed verification** (each failed on provenance, internal disclosure, entitlement, or outage checks; security
and P1 cases routed to specialist review). This verifies the runtime's guards, not model behavior.

Gates (`make eval-offline`): dataset validity and split hashes, challenge suite ran with zero unsafe drafts passing
verification, no rules errors, and no regression from [`evals/baselines/offline.json`](../evals/baselines/offline.json)
(rules route accuracy 0.9683 on 126 cases).

### Live smoke (measured subset on the local model)

Report: [`live-smoke-20261106T142718`](../evals/results/live-smoke-20261106T142718.md), commit `24c865b`, Ollama
0.40.14, `qwen3:4b-instruct` digest `0edcdef34593…`, Apple M5 (arm64, macOS), concurrency 1, one untimed warm-up call.
Cases: the six demos plus the first validation case of each category (12 cases x 3 systems = 36 pairs). **504 of the
540 planned case-system pairs were not run**; the test split is frozen and was not run.

| System | Cases | Route accuracy | Evidence recall@k | Provenance validity | Issue links | Forbidden-claim cases | Latency p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rules | 12 | 1.00 (12/12) | 0.75 (3/4) | n/a (no citations) | 1.00 (2/2) | 0 | 12 / 35 ms |
| rag | 12 | 0.67 (8/12) | 1.00 (4/4) | 0.73 (24/33) | 1.00 (2/2) | 0 | 3.7 / 6.9 s |
| agent | 12 | 0.67 (8/12) | 1.00 (4/4) | 1.00 (33/33) | 1.00 (2/2) | 0 | 22.2 / 31.9 s |

Observed agent failures: the Business-plan SSO question went to specialist review instead of an answer; the
disclosure-trap demo (an EXPORT_500 report that also asks for other customers' data) was answered instead of linked
to ENG-101 (no other-tenant information appeared); a new billing tax-rounding signature was routed to clarification
instead of a handoff; and an internal-only Slack delivery incident was answered instead of linked. RAG failures
included linking a known issue for the SSO question and for a vague export report.

Run-to-run variability: an earlier smoke run of the same cases on an uncommitted tree (not kept) routed the SSO
question correctly, so single-run results on 12 cases are noisy. Twelve cases cannot distinguish the systems
statistically.

### Interpretation

On this synthetic mix the rules baseline matches or beats both model-backed systems on routing, largely because the
tickets carry clean structured fields. The agent's measured advantages here are provenance (every cited source
existed and was customer-visible) and evidence recall; it costs about six times the RAG latency. These are smoke
results, not release gates: the proposed release gates (route macro F1 ≥ 0.85 on the frozen test split, ≥ 0.95 human
claim-support precision) remain unmeasured.

## Reproducing

```bash
make eval-offline                         # about 5 seconds; fails on gate violations
make eval-live-smoke                      # about 6 minutes on the development machine
uv --directory backend run python ../evals/runners/run.py --profile full --systems rules,rag,agent
```

The full profile covers 126 dev and validation cases per system. From the measured p50 latencies, the agent alone needs
roughly 126 x 22 s ≈ 46 minutes and RAG roughly 8 minutes. Add `--include-test` only for a final, frozen
configuration, and record that the test split was consumed. Import reports into the Evaluations page with **Import
reports from evals/results**.
