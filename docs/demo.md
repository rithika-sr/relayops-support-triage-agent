# Demo walkthrough

Prerequisites: `make setup`, the two Ollama models, `make seed-demo`, `make demo-dev` (web on :3030). Every page
shows the demo banner. Sign-in passwords are in
`.local/demo-credentials.json`; `make demo` prints the URLs and accounts without showing passwords.

## 1. Customer reports a problem

Sign in as `customer@northstar.local` (Northstar Logistics, Business plan, version 2.4). The portal shows only this
account's tickets, public help articles, and the published notifications incident banner. File a ticket: subject
"Fleet Planning CSV export keeps failing", area `exports`, error code `EXPORT_500`. The ticket page says replies appear
after review.

## 2. Support investigates

Sign in as `support@relayops.local`. The Inbox lists the ticket with its account and a live first-response countdown
(Business, normal priority: 12 elapsed hours). Open it: account entitlements and the target reasons are on the right.
Choose the **Bug investigation** playbook and **Investigate**.

The investigation workspace streams persisted events: extraction, up to four investigation turns with their stated
purposes, each tool call and observation, routing, the customer-evidence view, and verification. With the seeded
world the model typically links ENG-101 (EXPORT_500 on 2.4 with more than about 50k tasks). The evidence inspector
shows each source's visibility, version, and hashes; deployments carry a correlation-only note.

## 3. Review the exact version

Read the draft under **Customer will see exactly this**. **Review status** groups the checks: provenance (sources
exist, are customer-visible, and are current), policy (entitlements, disclosure, causal and outage claims, issue
links), claim support (each sentence's verdict and how it was reached: plan record, number in a cited source, local
model judgment, or not checked), and human review. Fix anything wrong (for example the export option is called
"Prepare in background") and **Save edit as version 2**; the edit is re-checked with typed rules, and claims the
sources could not confirm need the acknowledgment checkbox before **Approve and publish reply** is enabled. The worker executes once: the receipt says the reply was recorded in RelayOps only.

## 4. Customer sees the approved reply

Back in the portal the support reply appears; the ticket is waiting on the customer, not resolved. The staff ticket
shows the action receipt and the ENG-101 link.

## 5. Other curated scenarios

| Scenario | How to see it |
| --- | --- |
| Current policy beats an obsolete case | Ticket "Can we turn on SSO?" on Northstar (Business). The 2025 Business-SSO policy is superseded and excluded; the 2025 historical case is retrievable but lower authority; a reply claiming SSO is included fails the entitlement check. |
| Missing information | A vague "Export not working" ticket routes to clarification with questions the customer can answer. |
| Disclosure trap | Quillstack (a second organization) has same-keyword `EXPORT_500` records marked `QUILLSTACK-PRIVATE`; Acme has account-scoped runbooks. Neither appears in Northstar runs, searches, or counts. |
| New webhook handoff | Acme ticket with `WEBHOOK_SIG_MISMATCH` on 2.5: no matching issue, a webhooks deployment shortly before the errors (correlation only), error aggregates across two accounts; approving creates a local `LOCAL-n` engineering issue for integrations-platform. |
| Restart | Stop `make dev` while a run is investigating and start it again. After the job lease expires (up to 60 seconds) the worker reclaims the job and resumes the same thread from its last checkpoint. A run paused for review stays paused across restarts. |
| Recorded replay | On a finished run, **Recorded replay** re-presents its events with a banner; no model, tool, or action runs, and nothing can be approved. **Compare run** starts a new live run that needs its own review. |
| Incident constellation | Incidents: the `WEBHOOK_SIG_MISMATCH` candidate shows 3 tickets and 2 distinct accounts. **Confirm after review** creates a staff-only incident; only an admin can publish a public summary to customers. |

## 6. Admin

Sign in as `admin@relayops.local` for Audit, Evaluations (import the committed reports from `evals/results`),
playbook revisions, members, customer invitations (link shown once, never emailed), and read-scoped tokens.

## 7. Customer Help and Customer Success

As the customer, open **Help**, search "export rows limit", open an article, and answer **Did this answer your
question?** Choosing **No** opens a contact form that carries the article and search to support. The portal's
**Getting started** list fills in from what the account has done (sign-in, first ticket, first reviewed reply, a Help
article read, a second portal user).

As staff, **Customer Success** shows each account's counts and friction signals, weekly retention cohorts (weeks not
yet reachable show "pending"), opportunity cards with the rule and evidence behind each, and experiments on Help
ranking. In a demo instance these count demo records only and say so; an operational instance never counts them.
