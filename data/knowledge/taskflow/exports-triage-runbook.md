---
slug: exports-triage-runbook
title: Exports triage runbook
kind: runbook
visibility: internal
component: exports
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# Exports triage runbook

## Before escalating

Confirm the product version, the approximate task count, and the failure time. Check known issues for the exports component and the error aggregates for EXPORT_500.

## Known pattern

On 2.4, synchronous CSV exports above about 50,000 tasks can fail with EXPORT_500; tracked as a known issue. Recommend the background export as the workaround and link the ticket to the issue. Do not promise a fix date.
