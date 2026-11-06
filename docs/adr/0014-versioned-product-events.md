# 0014: A versioned product-event schema as the basis for Customer Success views

Status: accepted

## Context

Onboarding, adoption, retention, opportunities, and experiments all need the same facts about what customers did.
Ad-hoc counters would drift apart and invite numbers that were never measured.

## Decision

One `product_events` table with a versioned schema (`domain/events.py`, v1): each event name has fixed, typed
properties; unknown names, fields, or types are rejected. Events are deduplicated by an event ID unique per
organization (natural keys for app events, `import:` prefixed IDs for imports). Views compute from these rows and
from existing records only:

- Onboarding steps are complete when a qualifying record exists.
- Retention reports week k for a cohort only after every account in it could have reached week k; otherwise
  "pending", never 0%.
- Opportunity cards come from written rules with thresholds and show their evidence.
- Experiments have one surface (Help ranking), stable hash assignment, and hide results until every variant reaches
  a pre-registered minimum.

## Consequences

- Adding an event or property means a schema change; v2 will need a migration path for v1 rows.
- Free text is limited to the Help search query (truncated) so that knowledge gaps can be found.
