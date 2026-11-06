# 0012: Versioned service calendars, computed in local time and stored in UTC

Status: accepted

## Context

First-response targets were 24/7 elapsed hours. Support teams work in service hours in a time zone, with holidays,
and daylight-saving changes move UTC offsets twice a year.

## Decision

An admin defines weekly windows in an IANA time zone plus holidays. Each save creates an immutable version. Windows
are evaluated per local day and converted through `zoneinfo`, so a 09:00–17:00 window stays 09:00–17:00 local across
DST and a window spanning a skipped or repeated hour has its true length. Each ticket stores its due time in UTC and
the calendar version (`default@vN`) that produced it. Urgent targets stay 24/7 unless the calendar opts in.

## Consequences

- Changing the calendar never moves existing tickets' targets.
- Account-specific calendars are not supported; one calendar applies to the organization.
