"""Service calendars drive first-response targets; each ticket keeps the version that set its target."""

from __future__ import annotations

from datetime import datetime

from tests.agent_helpers import ADMIN, CUSTOMER, SUPPORT, client, seeded

WEEKDAYS = {d: [["09:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri")}


def _ticket(cust, support, severity="normal"):
    r = cust.post(
        "/api/tickets",
        json={"subject": "Question about exports", "body": "How do I export a board?", "reported_severity": severity},
    )
    assert r.status_code == 201, r.text
    assert "target" not in r.json()["ticket"]  # customers never see internal targets
    return support.get(f"/api/tickets/{r.json()['ticket']['id']}").json()["ticket"]


def test_calendar_versions_and_ticket_targets(db, tmp_path):
    creds = seeded(db, tmp_path)
    cust, support, admin = client(CUSTOMER, creds), client(SUPPORT, creds), client(ADMIN, creds)
    before = _ticket(cust, support)
    assert before["target"]["policy"]["basis"] == "24/7 elapsed hours"

    body = {"timezone": "America/New_York", "weekly": WEEKDAYS, "holidays": ["2026-11-26"]}
    assert support.post("/api/settings/calendars", json=body).status_code == 403
    bad = admin.post("/api/settings/calendars", json={**body, "timezone": "Eastern"})
    assert bad.status_code == 422 and "IANA" in bad.text
    v1 = admin.post("/api/settings/calendars", json=body).json()
    assert v1["ref"] == "default@v1"

    t1 = _ticket(cust, support)
    pol = t1["target"]["policy"]
    assert pol["basis"] == "service hours" and pol["calendar"] == "default@v1"
    assert pol["calendar_timezone"] == "America/New_York"
    urgent = _ticket(cust, support, severity="critical")
    assert urgent["target"]["policy"]["basis"] == "24/7 elapsed hours"  # urgent stays 24/7 by default

    v2 = admin.post("/api/settings/calendars", json={**body, "timezone": "Europe/London"}).json()
    listed = support.get("/api/settings/calendars").json()
    assert listed["active"] == "default@v2" and [v["version"] for v in listed["versions"]] == [2, 1]
    assert support.get(f"/api/tickets/{t1['id']}").json()["ticket"]["target"]["policy"]["calendar"] == "default@v1"
    assert v2["timezone"] == "Europe/London"

    pv = support.post("/api/settings/calendars/preview", json={"start": "2026-11-06T16:30:00+00:00", "hours": 1}).json()
    # Fri 16:30 London + 1h of 09:00-17:00 -> 30 min Friday, 30 min Monday 09:00-09:30.
    assert datetime.fromisoformat(pv["due_at"]) == datetime.fromisoformat("2026-11-09T09:30:00+00:00")

    assert admin.post("/api/settings/calendars/deactivate").json() == {"active": None}
    assert _ticket(cust, support)["target"]["policy"]["basis"] == "24/7 elapsed hours"
