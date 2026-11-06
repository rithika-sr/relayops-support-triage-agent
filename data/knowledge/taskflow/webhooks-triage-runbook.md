---
slug: webhooks-triage-runbook
title: Webhooks triage runbook
kind: runbook
visibility: internal
component: webhooks
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# Webhooks triage runbook

Collect the endpoint URL host (not secrets), the delivery ID from the delivery log, the response code, and when failures started.

A deployment shortly before failures began is a lead, not a root cause. State the timing as correlation in handoffs. Hand off to the integrations-platform team with the delivery IDs and the affected account count from error aggregates.
