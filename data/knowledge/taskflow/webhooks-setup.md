---
slug: webhooks-setup
title: Setting up webhooks and verifying signatures
kind: article
visibility: public
component: webhooks
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# Setting up webhooks and verifying signatures

Webhooks are available on Team, Business, and Enterprise plans. Create an endpoint under Settings, then Integrations, then Webhooks.

## Signatures

Every delivery includes the header X-TaskFlow-Signature. Compute an HMAC-SHA256 of the raw request body with your endpoint secret and compare it with the header value using a constant-time comparison.

## Retries

Failed deliveries are retried with exponential backoff up to 8 times over roughly 24 hours. A delivery fails when your endpoint returns a non-2xx status or does not respond within 10 seconds.

## Delivery log

Settings, then Webhooks, then Delivery log shows the last 7 days of attempts with response codes.
