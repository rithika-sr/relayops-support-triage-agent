---
slug: support-response-targets
title: Support response targets
kind: policy
visibility: public
valid_from: 2026-07-01T00:00:00Z
---
# Support response targets

All TaskFlow Cloud response targets are measured in elapsed hours, 24 hours a day, 7 days a week. They are first-response targets, not resolution commitments.

## First-response targets by plan

| Plan | Urgent | High | Normal | Low |
| --- | --- | --- | --- | --- |
| Starter | 24h | 24h | 48h | 72h |
| Team | 8h | 12h | 24h | 48h |
| Business | 2h | 4h | 12h | 24h |
| Enterprise | 1h | 2h | 8h | 12h |

## How priority is set

Priority starts from the severity the customer selects. A ticket that describes critical impact, such as an outage for all users, is raised to at least High and flagged for urgent review. Urgent review does not mean TaskFlow has confirmed an outage; confirmation comes from the incident process.

Security-sensitive reports are routed to restricted specialist review and are handled at High priority or above.
