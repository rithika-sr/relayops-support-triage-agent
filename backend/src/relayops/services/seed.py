"""Idempotent seeding of the synthetic demo world and demo identities.

Passwords are generated once, stored hashed in the database, and written in plaintext only to the
git-ignored `.local/demo-credentials.json` (mode 0600). Re-running keeps existing passwords.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.agents.llm import Provider, get_provider
from relayops.core.config import REPO_ROOT, get_settings
from relayops.core.security import content_hash, hash_password, verify_password
from relayops.domain.playbooks import DEFAULT_PLAYBOOKS, PlaybookConfig
from relayops.domain.policies import decide_target
from relayops.models import (
    ComponentOwner,
    CustomerAccount,
    Deployment,
    EngineeringIssue,
    ErrorAggregate,
    Incident,
    Membership,
    Organization,
    Playbook,
    PlaybookRevision,
    Ticket,
    TicketIssueLink,
    TicketMessage,
    User,
)
from relayops.services import knowledge

DATA = REPO_ROOT / "data"
CREDENTIALS = REPO_ROOT / ".local" / "demo-credentials.json"


def world_anchor() -> datetime:
    raw = get_settings().world_anchor
    if raw == "now":
        return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    world = json.loads((DATA / "fixtures" / "world.json").read_text())
    return datetime.fromisoformat((raw or world["default_anchor"]).replace("Z", "+00:00"))


def _front_matter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("document is missing front matter")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(2)


def _dt(raw: str | None) -> datetime | None:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else None


def _load_credentials(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _save_credentials(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(path, 0o600)


def _seed_users(db: Session, org: Organization, users: list[dict[str, Any]], creds: dict[str, Any]) -> None:
    accounts = creds.setdefault("accounts", {})
    for u in users:
        email = u["email"]
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        saved = accounts.get(email, {}).get("password")
        if user is None:
            password = saved or secrets.token_urlsafe(18)
            user = User(email=email, name=u["name"], password_hash=hash_password(password))
            db.add(user)
            db.flush()
        elif not saved or not verify_password(user.password_hash, saved):
            # Plaintext is not recoverable from the hash; issue a new one and record it locally.
            password = secrets.token_urlsafe(18)
            user.password_hash = hash_password(password)
        else:
            password = saved
        m = db.execute(
            select(Membership).where(Membership.user_id == user.id, Membership.organization_id == org.id)
        ).scalar_one_or_none()
        if m is None:
            db.add(
                Membership(
                    user_id=user.id, organization_id=org.id, role=u["role"], customer_account_id=u.get("account")
                )
            )
        accounts[email] = {
            "password": password,
            "role": u["role"],
            "organization": org.name,
            **({"customer_account": u["account"]} if u.get("account") else {}),
        }


def _upsert(db: Session, model: Any, id_: str, **values: Any) -> Any:
    row = db.get(model, id_)
    if row is None:
        row = model(id=id_, **values)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
    return row


def _seed_ticket(
    db: Session,
    org_id: str,
    acct: CustomerAccount,
    t: dict[str, Any],
    anchor: datetime,
    historical: bool,
    issues: dict[str, EngineeringIssue],
    author: User | None,
) -> None:
    existing = db.execute(
        select(Ticket).where(Ticket.organization_id == org_id, Ticket.external_event_id == t["external_event_id"])
    ).scalar_one_or_none()
    if existing is not None:
        return
    created = anchor + timedelta(hours=t["offset_hours"])
    d = decide_target(
        plan=acct.plan,
        reported_severity=t.get("reported_severity", "normal"),
        subject=t["subject"],
        body=t["body"],
        created_at=created,
    )
    number = (
        db.execute(
            select(func.coalesce(func.max(Ticket.number), 1000)).where(Ticket.organization_id == org_id)
        ).scalar_one()
        + 1
    )
    org_row = db.get(Organization, org_id)
    dc = org_row.data_class if org_row else "unknown"
    ticket = Ticket(
        data_class=dc,
        source_kind="seed",
        source_system="relayops-demo-seed",
        received_at=created,
        organization_id=org_id,
        customer_account_id=acct.id,
        number=number,
        subject=t["subject"],
        status="resolved" if historical else "open",
        priority=d.priority,
        reported_severity=t.get("reported_severity", "normal"),
        component=t.get("component"),
        product_version=t.get("product_version"),
        error_code=t.get("error_code"),
        restricted=d.restricted,
        is_historical=historical,
        resolution_summary=t.get("resolution_summary"),
        tags=[f"family:{t['family_id']}"] if t.get("family_id") else [],
        external_event_id=t["external_event_id"],
        created_at=created,
        updated_at=created,
        first_response_due_at=d.due_at,
        target_policy=d.as_policy(),
        first_responded_at=created + timedelta(hours=1) if historical else None,
        resolved_at=created + timedelta(hours=20) if historical else None,
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketMessage(
            data_class=dc,
            source_kind="seed",
            ticket_id=ticket.id,
            organization_id=org_id,
            customer_account_id=acct.id,
            author_kind="customer",
            visibility="customer",
            body=t["body"],
            created_at=created,
        )
    )
    if historical:
        db.add(
            TicketMessage(
                data_class=dc,
                source_kind="seed",
                ticket_id=ticket.id,
                organization_id=org_id,
                customer_account_id=acct.id,
                author_user_id=author.id if author else None,
                author_kind="staff",
                visibility="customer",
                body=t["resolution_summary"],
                created_at=created + timedelta(hours=1),
            )
        )
        key = t.get("linked_issue")
        if key and key in issues:
            kind = "feature_request" if issues[key].kind == "feature" else "known_issue"
            db.add(
                TicketIssueLink(organization_id=org_id, ticket_id=ticket.id, issue_id=issues[key].id, link_kind=kind)
            )


def _seed_errors(db: Session, org_id: str, series: list[dict[str, Any]], anchor: datetime) -> None:
    if db.execute(select(func.count(ErrorAggregate.id)).where(ErrorAggregate.organization_id == org_id)).scalar_one():
        return
    rng = random.Random(f"errors:{org_id}")
    for s in series:
        lo, hi = s["per_hour"]
        for h in range(s["start_offset"], s["end_offset"]):
            for acct in s["accounts"]:
                n = rng.randint(lo, hi)
                if n:
                    db.add(
                        ErrorAggregate(
                            id=f"err_{org_id}_{s['signature']}_{acct}_{h}".lower()[:64],
                            organization_id=org_id,
                            customer_account_id=acct,
                            component=s["component"],
                            error_signature=s["signature"],
                            product_version=s["product_version"],
                            bucket_start=anchor + timedelta(hours=h),
                            count=n,
                        )
                    )


class SeedRefused(RuntimeError):
    pass


def seed(db: Session, provider: Provider | None = None, credentials_path: Path | None = None) -> dict[str, Any]:
    """Load the synthetic world. Only allowed in a database initialized for demo or test data."""
    from relayops.core.instance import recorded_mode

    mode = recorded_mode(db)
    if mode not in ("demo", "test") or get_settings().data_mode != mode:
        raise SeedRefused(
            f"refusing to seed sample data: database mode is {mode!r}, configured mode is "
            f"{get_settings().data_mode!r}. Use make seed-demo, which targets the separate demo database."
        )
    data_class = mode
    provider = provider or get_provider()
    world = json.loads((DATA / "fixtures" / "world.json").read_text())
    history = json.loads((DATA / "fixtures" / "historical_tickets.json").read_text())["tickets"]
    anchor = world_anchor()
    existing = db.get(Organization, world["organizations"][0]["id"])
    if existing is not None and (existing.settings or {}).get("world_anchor"):
        # Keep timestamps consistent with rows already seeded; reset the database to re-anchor.
        anchor = datetime.fromisoformat(existing.settings["world_anchor"])
    creds_path = credentials_path or CREDENTIALS
    creds = _load_credentials(creds_path)
    stats: dict[str, Any] = {"anchor": anchor.isoformat(), "documents_changed": 0}

    for o in world["organizations"]:
        org = _upsert(db, Organization, o["id"], name=o["name"], slug=o["slug"], data_class=data_class)
        if "world_anchor" not in (org.settings or {}):
            org.settings = {
                **(org.settings or {}),
                "world_anchor": anchor.isoformat(),
                "world_version": world["world_version"],
            }
        db.flush()
        accounts = {
            a["id"]: _upsert(
                db,
                CustomerAccount,
                a["id"],
                organization_id=org.id,
                name=a["name"],
                plan=a["plan"],
                product_version=a["product_version"],
                region=a["region"],
            )
            for a in o["accounts"]
        }
        db.flush()
        _seed_users(db, org, o["users"], creds)
        for own in o["owners"]:
            row = db.execute(
                select(ComponentOwner).where(
                    ComponentOwner.organization_id == org.id, ComponentOwner.component == own["component"]
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(ComponentOwner(organization_id=org.id, **own))
        issues: dict[str, EngineeringIssue] = {}
        for i in o["issues"]:
            issue = db.execute(
                select(EngineeringIssue).where(
                    EngineeringIssue.organization_id == org.id, EngineeringIssue.key == i["key"]
                )
            ).scalar_one_or_none()
            if issue is None:
                issue = EngineeringIssue(
                    organization_id=org.id,
                    owner_team=next((x["team"] for x in o["owners"] if x["component"] == i["component"]), "unassigned"),
                    created_at=anchor - timedelta(days=30),
                    updated_at=anchor - timedelta(days=2),
                    **i,
                )
                db.add(issue)
            issues[i["key"]] = issue
        for n, d in enumerate(o["deployments"]):
            _upsert(
                db,
                Deployment,
                f"dep_{org.id}_{n}"[:64],
                organization_id=org.id,
                component=d["component"],
                version=d["version"],
                deployed_at=anchor + timedelta(hours=d["offset_hours"]),
                summary=d["summary"],
            )
        for inc in o["incidents"]:
            _upsert(
                db,
                Incident,
                inc["id"],
                organization_id=org.id,
                title=inc["title"],
                component=inc["component"],
                status=inc["status"],
                severity=inc["severity"],
                started_at=anchor + timedelta(hours=inc["start_offset"]),
                resolved_at=anchor + timedelta(hours=inc["resolved_offset"]) if inc["resolved_offset"] else None,
                error_signature=inc["error_signature"],
                affected_versions=inc["affected_versions"],
                internal_notes=inc["internal_notes"],
                public_summary=inc["public_summary"],
                public_visible=inc["public_visible"],
            )
        db.flush()
        _seed_errors(db, org.id, o["error_series"], anchor)
        staff = (
            db.execute(
                select(User)
                .join(Membership, Membership.user_id == User.id)
                .where(Membership.organization_id == org.id, Membership.role == "support")
            )
            .scalars()
            .first()
        )
        for t in o["open_tickets"]:
            _seed_ticket(db, org.id, accounts[t["account"]], t, anchor, False, issues, staff)
        if org.id == "org_taskflow":
            for t in history:
                _seed_ticket(db, org.id, accounts[t["account"]], t, anchor, True, issues, staff)
        for key, spec in DEFAULT_PLAYBOOKS.items():
            pb = db.execute(
                select(Playbook).where(Playbook.organization_id == org.id, Playbook.key == key)
            ).scalar_one_or_none()
            if pb is None:
                cfg = PlaybookConfig.model_validate(spec["config"]).model_dump(mode="json")
                pb = Playbook(organization_id=org.id, key=key, name=spec["name"], description=spec["description"])
                db.add(pb)
                db.flush()
                db.add(
                    PlaybookRevision(
                        playbook_id=pb.id,
                        organization_id=org.id,
                        revision=1,
                        config=cfg,
                        config_hash=content_hash(cfg),
                        created_by="seed",
                    )
                )
        db.flush()

    # Knowledge documents and approved historical case summaries.
    folder_org = {"taskflow": "org_taskflow", "quillstack": "org_quillstack"}
    for folder, org_id in folder_org.items():
        for doc_path in sorted((DATA / "knowledge" / folder).rglob("*.md")):
            meta, body = _front_matter(doc_path.read_text())
            doc, _, changed = knowledge.ingest(
                db,
                None,
                knowledge.DocumentInput(
                    slug=meta["slug"],
                    title=meta["title"],
                    kind=meta["kind"],
                    visibility=meta["visibility"],
                    content=body,
                    component=meta.get("component") or None,
                    product_versions=tuple(v.strip() for v in meta.get("product_versions", "").split(",") if v.strip()),
                    customer_account_id=meta.get("account") or None,
                    valid_from=_dt(meta.get("valid_from")),
                    valid_to=_dt(meta.get("valid_to")),
                    source_filename=str(doc_path.relative_to(REPO_ROOT)),
                ),
                organization_id=meta.get("org", org_id),
                provider=provider,
            )
            if meta.get("status") and doc.status != meta["status"]:
                doc.status = meta["status"]
            stats["documents_changed"] += int(changed)
    for t in history:
        if not t.get("case_document"):
            continue
        created = anchor + timedelta(hours=t["offset_hours"])
        body = (
            f"# Case: {t['subject']}\n\nProduct version: {t['product_version']}. Component: {t['component']}.\n\n"
            f"## Customer report\n\n{t['body']}\n\n## Approved resolution\n\n{t['resolution_summary']}\n"
        )
        _, _, changed = knowledge.ingest(
            db,
            None,
            knowledge.DocumentInput(
                slug=f"case-{t['external_event_id']}",
                title=f"Case: {t['subject']}",
                kind="historical_case",
                visibility="internal",
                content=body,
                component=t["component"],
                product_versions=(t["product_version"],),
                valid_from=created,
                source_filename="data/fixtures/historical_tickets.json",
            ),
            organization_id="org_taskflow",
            provider=provider,
        )
        stats["documents_changed"] += int(changed)

    s = get_settings()
    creds["urls"] = {
        "web": s.web_origin,
        "login": f"{s.web_origin}/login",
        "api": s.api_origin,
        "api_docs": f"{s.api_origin}/api/docs",
    }
    creds["note"] = "Local demo credentials generated by `make seed`. Never commit this file."
    _save_credentials(creds_path, creds)
    stats["credentials_file"] = str(creds_path)
    stats["counts"] = {
        "tickets": db.execute(select(func.count(Ticket.id))).scalar_one(),
        "documents": db.execute(
            select(func.count()).select_from(select(knowledge.KnowledgeDocument.id).subquery())
        ).scalar_one(),
        "issues": db.execute(select(func.count(EngineeringIssue.id))).scalar_one(),
        "error_rows": db.execute(select(func.count(ErrorAggregate.id))).scalar_one(),
    }
    return stats


def main() -> None:
    from relayops.core.db import session_scope

    try:
        with session_scope() as db:
            print(json.dumps(seed(db), indent=2, default=str))
    except SeedRefused as exc:
        print(f"error: {exc}")
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
