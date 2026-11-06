# 0009: Data modes per database, and provenance set by the server

Status: accepted

## Context

The first release seeded synthetic records into the same database people would use for real work, and nothing on a
record said whether it was real. Demo numbers could leak into analytics, and a client could claim a record was real.

## Decision

- Each database records one data mode (`operational`, `demo`, or `test`) in `instance_metadata` at initialization.
  The API and worker refuse to start when the configured mode differs from the recorded one. Operational is the
  default and starts empty; operational mode refuses the fixture model provider and development secrets.
- `make seed-demo` writes only to the separate demo database and refuses an operational one. A demo instance shows a
  persistent banner.
- Records carry `data_class` and `source_kind` (portal, manual, import, connector, seed), derived on the server from
  the organization and the request path. No request model exposes them.
- Migration 0002 classified existing rows: organizations created by the seed became demo, children followed their
  organization. The pre-existing local database was backed up first and became the demo instance.

## Consequences

- Analytics count only operational records in an operational instance (or only the instance's own class), and say
  how many records of other classes were left out. Unknown is never counted.
- Moving records between modes is not supported; that is deliberate.
