# Worked example: one ticket, end to end

Captured on 2026-11-06 18:13 UTC by `scripts/worked_example.py` against the local **demo** instance (`http://localhost:8030`), on the real
local model. Every quoted value below was copied from an API response during that run; nothing was edited by hand
except this prose. The records are synthetic demo data. Re-running the script produces a new ticket and, because the
model is not deterministic across versions, possibly different wording.

Model and runtime as reported by `/api/settings/health`:

```json
{
  "provider": "ollama",
  "reachable": true,
  "chat_model": "qwen3:4b-instruct",
  "chat_model_present": true,
  "embed_model": "embeddinggemma",
  "embed_model_present": true
}
```

## 1. The customer files a ticket in the portal

```json
{
  "subject": "Fleet Planning CSV export keeps failing",
  "body": "Exporting our Fleet Planning project (about 80k tasks) to CSV fails with EXPORT_500 every time since this morning. Smaller projects export fine. Is this a known problem, and is there a workaround?",
  "component": "exports",
  "error_code": "EXPORT_500",
  "reported_severity": "high"
}
```

The portal response shows the customer only their own ticket; staff see the computed target:

```json
{
  "number": 1139,
  "priority": "high",
  "target": {
    "due_at": "2026-11-06T22:13:04.573815+00:00",
    "responded_at": null,
    "state": "due",
    "seconds_remaining": 14399,
    "policy": {
      "policy_version": "2026.11-r1",
      "priority": "high",
      "hours": 4,
      "basis": "24/7 elapsed hours",
      "calendar": null,
      "calendar_timezone": null,
      "reasons": [
        "customer-reported severity: high",
        "business plan first-response target for high: 4h elapsed"
      ],
      "urgent_review": false,
      "restricted": false
    }
  }
}
```

## 2. Support starts the bug playbook

The run reached review in 39 s with these lookups, tool calls, and decisions (from `run_events`):

- `trusted_lookup` rule `known_issue_signature_version` (applied: False): ENG-101 matches the corroborated error signature and affected version 2.4.
- `decision` {"turn": 1, "purpose": "Verify if there is a recent deployment around the time the error started that could correlate with the EXPORT_500 issue in version 2.4", "action": "call_tools", "requested": [{"tool": "get_recent_
- `tool_call` get_recent_deployments {"component": "exports", "lookback_hours": 96}
- `tool_result` get_recent_deployments: empty, 0 evidence item(s)
- `tool_call` get_error_aggregates {"component": "exports", "error_signature": "EXPORT_500", "lookback_hours": 96}
- `tool_result` get_error_aggregates: stale, 1 evidence item(s)
- `decision` {"turn": 2, "purpose": "Verify if the error signature and version match an existing engineering issue to confirm known root cause and provide a workaround", "action": "call_tools", "requested": [{"tool": "search_engineer
- `tool_call` search_engineering_issues {"query": "EXPORT_500", "component": "exports", "product_version": "2.4"}
- `tool_result` search_engineering_issues: ok, 5 evidence item(s)
- `decision` {"turn": 3, "purpose": "Verify if the error signature EXPORT_500 in version 2.4 is correlated with a recent incident involving the exports component to confirm if the issue is active and widespread.", "action": "call_too
- `tool_call` get_incident_snapshot {"component": "exports"}
- `tool_result` get_incident_snapshot: ok, 1 evidence item(s)
- `decision` {"turn": 4, "purpose": "Verify if the error signature EXPORT_500 in version 2.4 is directly linked to a known engineering issue with a matching version and signature, to confirm a known problem and potential workaround."
- `tool_result` customer_evidence_view: ok, 4 evidence item(s)

Usage recorded on the run: `{"turns": 4, "tool_calls": 4, "model_calls": 7, "repairs": 0}`

Route: **link_existing_issue** (link_engineering_issue). Draft (version 1):

```text
The team is aware of the issue with large CSV exports failing. For your Business plan, the maximum rows per synchronous export is 250,000, and your project has about 80,000 tasks, which is within this limit. However, if the export still fails, it may be due to system performance under load. A documented workaround is to use the asynchronous export option, available in version 2.4 and above, which allows larger exports to complete without failing. You can access this by selecting 'Background Export' when exporting a project. This option is available on all plans including Business.
```

## 3. Verification of version 1

Status: **failed**. Claim verifier: `{"kind": "local_model", "model": "qwen3:4b-instruct", "digest": "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0", "timeout_seconds": 30.0}`.

| Check | Status | Detail |
| --- | --- | --- |
| required_fields | pass | complete |
| provenance | pass | 2 reply citations exist |
| reply_visibility | pass | reply cites public evidence only |
| source_currency | pass | all cited sources current |
| no_internal_disclosure | pass | none found |
| entitlement_sso | pass | consistent with plan entitlements (sso=False) |
| no_unsupported_root_cause | pass | no causal claims stated as fact |
| no_unconfirmed_outage | pass | ok |
| issue_link | pass | ENG-101 affected_versions=['2.4'], ticket version=2.4 |
| claim_support | fail | 1 contradicted; 2 of 5 substantive claims uncertain (typed checks plus a local model judgment; not proof) |

| Sentence | Kind | Verdict | Method |
| --- | --- | --- | --- |
| The team is aware of the issue with large CSV exports failing. | factual | insufficient_evidence | semantic_model |
| For your Business plan, the maximum rows per synchronous export is 250,000, and your project has about 80,000  | factual | contradicted | typed_number |
| However, if the export still fails, it may be due to system performance under load. | hypothesis | insufficient_evidence | semantic_model |
| A documented workaround is to use the asynchronous export option, available in version 2.4 and above, which al | factual | supported | semantic_model |
| You can access this by selecting 'Background Export' when exporting a project. | factual | insufficient_evidence | semantic_model |
| This option is available on all plans including Business. | factual | supported | semantic_model |

## 4. The reviewer edits, then approves the exact version

**Who acted:** the reviewer steps below were performed by the capture script on behalf of a support user; no human
reviewed this draft. The script removed the 1 sentence(s) verification marked contradicted:

- ~~For your Business plan, the maximum rows per synchronous export is 250,000, and your project has about 80,000 tasks, which is within this limit.~~

and appended one sentence about the documented workaround. That created version 2 (status
`passed`). Edited text is checked with typed rules only; the semantic verifier does not run on
human-authored text:

| Sentence | Kind | Verdict | Method |
| --- | --- | --- | --- |
| The team is aware of the issue with large CSV exports failing. | factual | unavailable | not_run |
| However, if the export still fails, it may be due to system performance under load. | hypothesis | not_a_claim | none |
| A documented workaround is to use the asynchronous export option, available in version 2.4 and above, which al | factual | unavailable | not_run |
| You can access this by selecting 'Background Export' when exporting a project. | factual | unavailable | not_run |
| This option is available on all plans including Business. | factual | unavailable | not_run |
| If you need the data now, choose Export > Prepare in background; the download link is emailed. | factual | unavailable | not_run |

Uncertain substantive claims on version 2: 5.
The reviewer acknowledged them at approval (the API refuses approval otherwise).

Approval response:

```json
{
  "review_id": "rev_3e1f89fac5484f06b57a",
  "binding_hash": "56612175d6b1ee8e22f5b6f375811084903a2cf0a231c6f16b24f610320a9e36",
  "status": "approved",
  "note": "Queued for execution by the worker; the action runs once."
}
```

## 5. The action runs once

Final run status: **completed**. Action record:

```json
{
  "kind": "link_engineering_issue",
  "status": "succeeded",
  "adapter": "local",
  "receipt": {
    "mode": "local",
    "note": "Recorded in RelayOps only. No email or external write.",
    "customer_message_id": "msg_66f49f1a37454a599ee8",
    "engineering_issue_id": "iss_8a57af157d884fb4a779",
    "engineering_issue_key": "ENG-101",
    "already_linked": false
  }
}
```

## 6. What the customer sees

The customer's ticket view now has 2 message(s); the latest is exactly the approved version 2:

```text
The team is aware of the issue with large CSV exports failing. However, if the export still fails, it may be due to system performance under load. A documented workaround is to use the asynchronous export option, available in version 2.4 and above, which allows larger exports to complete without failing. You can access this by selecting 'Background Export' when exporting a project. This option is available on all plans including Business.

If you need the data now, choose Export > Prepare in background; the download link is emailed.
```

Ticket status for the customer: `pending_customer` (a reply never resolves a ticket by itself).

## Reading this example

Captured at commit `99b07ad` with the default bug playbook, which uses the **adaptive** path (`execution=agent`):
the precheck found ENG-101 but did not decide the route (`applied: False`); the model investigated and reached
the same route on its own.

- **Reported by the customer:** the export failure, `EXPORT_500`, about 80k tasks, "since this morning". These stay
  reported observations; the version (2.4) is the account's recorded version.
- **Verified against records:** ENG-101's signature and affected version match (code check `issue_link`); every
  cited source exists, is customer-visible, and is current; no SSO, outage, causal, or internal-identifier claim
  slipped through.
- **Contradicted and blocked:** the draft's row-limit sentence conflicted with the cited source (typed number
  check). Verification failed, and the API refused approval until that sentence was removed.
- **Estimated by the local model, not proven:** two sentences were judged supported and four were insufficient
  evidence. After the edit, none of the remaining sentences were re-checked semantically (reviewer text gets typed
  checks only), so the approval required acknowledging five unconfirmed claims.
- **Internal only:** ENG-101, error aggregates, and the incident snapshot. The customer reply names none of them.
- **Customer-visible:** only the approved version 2, as a message in the portal; no email was sent and the ticket
  waits on the customer.

What a person should have done here that the script did not: the approved text still says "Background Export" and
calls it an "asynchronous export option", which the help article calls **Prepare in background**. The verifier did
not catch that wording, and the scripted reviewer accepted unconfirmed claims wholesale. Human review is the
check that remains; this example is evidence of the controls, not of draft quality.
