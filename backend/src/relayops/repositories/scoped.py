"""Scoped data access. Every query that reaches tenant data passes through these filters.

Organization is always applied. Customer principals are additionally restricted to their own
customer account and to customer-visible records. Callers never pass organization IDs in.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from relayops.domain.scope import AccessDenied, NotFound, Principal
from relayops.models import (
    Artifact,
    CustomerAccount,
    EngineeringIssue,
    Incident,
    InvestigationRun,
    KnowledgeDocument,
    Proposal,
    Ticket,
    TicketMessage,
)

T = TypeVar("T")


def require_staff(p: Principal) -> None:
    if not p.is_staff:
        raise AccessDenied("staff role required")


def require_admin(p: Principal) -> None:
    if not p.is_admin:
        raise AccessDenied("admin role required")


def tickets(p: Principal) -> Select[Ticket]:
    stmt = select(Ticket).where(Ticket.organization_id == p.organization_id)
    if not p.is_staff:
        stmt = stmt.where(Ticket.customer_account_id == p.customer_account_id, Ticket.is_historical.is_(False))
    return stmt


def messages(p: Principal, ticket_id: str) -> Select[TicketMessage]:
    stmt = select(TicketMessage).where(
        TicketMessage.organization_id == p.organization_id, TicketMessage.ticket_id == ticket_id
    )
    if not p.is_staff:
        stmt = stmt.where(
            TicketMessage.customer_account_id == p.customer_account_id, TicketMessage.visibility == "customer"
        )
    return stmt.order_by(TicketMessage.created_at, TicketMessage.id)


def accounts(p: Principal) -> Select[CustomerAccount]:
    stmt = select(CustomerAccount).where(CustomerAccount.organization_id == p.organization_id)
    if not p.is_staff:
        stmt = stmt.where(CustomerAccount.id == p.customer_account_id)
    return stmt


def documents(p: Principal) -> Select[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.organization_id == p.organization_id)
    if not p.is_staff:
        stmt = stmt.where(
            KnowledgeDocument.visibility == "public",
            KnowledgeDocument.kind != "historical_case",
            or_(
                KnowledgeDocument.customer_account_id.is_(None),
                KnowledgeDocument.customer_account_id == p.customer_account_id,
            ),
        )
    return stmt


def issues(p: Principal) -> Select[EngineeringIssue]:
    stmt = select(EngineeringIssue).where(EngineeringIssue.organization_id == p.organization_id)
    return stmt if p.is_staff else stmt.where(false())


def incidents(p: Principal) -> Select[Incident]:
    stmt = select(Incident).where(Incident.organization_id == p.organization_id)
    if not p.is_staff:
        stmt = stmt.where(Incident.public_visible.is_(True))
    return stmt


def runs(p: Principal) -> Select[InvestigationRun]:
    stmt = select(InvestigationRun).where(InvestigationRun.organization_id == p.organization_id)
    return stmt if p.is_staff else stmt.where(false())


def proposals(p: Principal) -> Select[Proposal]:
    stmt = select(Proposal).where(Proposal.organization_id == p.organization_id)
    return stmt if p.is_staff else stmt.where(false())


def artifacts(p: Principal) -> Select[Artifact]:
    stmt = select(Artifact).where(Artifact.organization_id == p.organization_id)
    return stmt if p.is_staff else stmt.where(false())


def one[T](db: Session, stmt: Select[T], what: str) -> T:
    """Fetch exactly one scoped row. Out-of-scope rows are indistinguishable from missing ones."""
    row = db.execute(stmt.limit(1)).scalar_one_or_none()
    if row is None:
        raise NotFound(f"{what} not found")
    return row


def get_ticket(db: Session, p: Principal, ticket_id: str, *, for_update: bool = False) -> Ticket:
    stmt = tickets(p).where(Ticket.id == ticket_id)
    if for_update:
        stmt = stmt.with_for_update()
    return one(db, stmt, "ticket")


def get_account(db: Session, p: Principal, account_id: str) -> CustomerAccount:
    return one(db, accounts(p).where(CustomerAccount.id == account_id), "customer account")


def get_run(db: Session, p: Principal, run_id: str) -> InvestigationRun:
    return one(db, runs(p).where(InvestigationRun.id == run_id), "investigation")


def get_proposal(db: Session, p: Principal, proposal_id: str, *, for_update: bool = False) -> Proposal:
    stmt = proposals(p).where(Proposal.id == proposal_id)
    if for_update:
        stmt = stmt.with_for_update()
    return one(db, stmt, "proposal")


def get_document(db: Session, p: Principal, doc_id: str) -> KnowledgeDocument:
    return one(db, documents(p).where(KnowledgeDocument.id == doc_id), "document")


def get_artifact(db: Session, p: Principal, artifact_id: str) -> Artifact:
    return one(db, artifacts(p).where(Artifact.id == artifact_id), "artifact")


def get_incident(db: Session, p: Principal, incident_id: str) -> Incident:
    return one(db, incidents(p).where(Incident.id == incident_id), "incident")
