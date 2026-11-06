---
slug: plan-entitlements
title: Plan entitlements (current)
kind: policy
visibility: public
valid_from: 2026-07-01T00:00:00Z
---
# Plan entitlements

This policy is effective from 1 July 2026 and replaces all earlier entitlement summaries.

## Single sign-on and provisioning

SAML single sign-on (SSO) and SCIM provisioning are included only in the Enterprise plan. Starter, Team, and Business plans do not include SSO. Business customers who need SSO must upgrade to Enterprise.

## Exports

| Plan | Maximum rows per synchronous export |
| --- | --- |
| Starter | 10,000 |
| Team | 50,000 |
| Business | 250,000 |
| Enterprise | 1,000,000 |

Exports larger than 50,000 tasks should use the asynchronous export option, available on every plan from version 2.4.

## Webhooks

Webhooks are available on Team, Business, and Enterprise plans.

## Audit log retention

Starter 7 days, Team 30 days, Business 90 days, Enterprise 365 days.
