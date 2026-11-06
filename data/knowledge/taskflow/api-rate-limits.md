---
slug: api-rate-limits
title: API rate limits
kind: article
visibility: public
component: api
product_versions: 2.4, 2.5
valid_from: 2026-06-01T00:00:00Z
---
# API rate limits

The REST API allows 600 requests per minute per token. Responses over the limit return HTTP 429 with the headers X-RateLimit-Remaining and Retry-After. Back off for the Retry-After interval before retrying.
