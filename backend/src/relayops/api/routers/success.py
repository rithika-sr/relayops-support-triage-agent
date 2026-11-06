"""Customer self-service Help (portal), Customer Success views (staff), events import, and experiments."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.api.deps import DB, admin_principal, current_principal, staff_principal
from relayops.domain.scope import AccessDenied, Principal, ValidationFailed
from relayops.models import Experiment
from relayops.services import events, experiments, help, success
from relayops.services.tickets import analytics_classes

router = APIRouter(tags=["success"])


class FeedbackBody(BaseModel):
    helpful: bool


class EscalateBody(BaseModel):
    subject: str = Field(min_length=3, max_length=300)
    body: str = Field(min_length=1, max_length=10_000)
    document_id: str | None = None
    query: str | None = Field(default=None, max_length=200)


class EventImportBody(BaseModel):
    items: list[dict[str, Any]]
    dry_run: bool = True


class ExperimentBody(BaseModel):
    key: str
    hypothesis: str = Field(max_length=2000)
    variants: list[str]
    min_accounts_per_variant: int = 50


@router.get("/portal/help/search")
def help_search(q: str, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    return help.search(db, p, q)


@router.get("/portal/help/articles/{document_id}")
def help_article(document_id: str, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    return help.article(db, p, document_id)


@router.post("/portal/help/articles/{document_id}/feedback")
def help_feedback(
    document_id: str, body: FeedbackBody, p: Principal = Depends(current_principal), db: Session = DB
) -> dict[str, Any]:
    return help.feedback(db, p, document_id, body.helpful)


@router.post("/portal/help/contact", status_code=201)
def help_contact(body: EscalateBody, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    return help.escalate(db, p, subject=body.subject, body=body.body, document_id=body.document_id, query=body.query)


@router.get("/portal/onboarding")
def portal_onboarding(p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    if p.is_staff or not p.customer_account_id:
        raise AccessDenied("customer portal only")
    return success.onboarding(db, p, p.customer_account_id)


@router.get("/success/accounts")
def cs_accounts(days: int = 30, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return success.accounts(db, p, max(1, min(days, 180)))


@router.get("/success/accounts/{account_id}/onboarding")
def cs_onboarding(account_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return success.onboarding(db, p, account_id)


@router.get("/success/retention")
def cs_retention(weeks: int = 8, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return success.retention(db, p, max(1, min(weeks, 26)))


@router.get("/success/opportunities")
def cs_opportunities(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return success.opportunities(db, p)


@router.post("/events/import")
def import_events(body: EventImportBody, p: Principal = Depends(admin_principal), db: Session = DB) -> dict[str, Any]:
    return events.import_events(db, p, body.items, dry_run=body.dry_run)


@router.get("/experiments")
def list_experiments(p: Principal = Depends(staff_principal), db: Session = DB) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Experiment).where(Experiment.organization_id == p.organization_id).order_by(Experiment.created_at.desc())
    ).scalars()
    return [{**experiments.as_dict(e), "results": experiments.results(db, p, e, analytics_classes())} for e in rows]


@router.post("/experiments", status_code=201)
def create_experiment(
    body: ExperimentBody, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    return experiments.as_dict(
        experiments.create(
            db,
            p,
            key=body.key,
            hypothesis=body.hypothesis,
            variants=body.variants,
            min_accounts_per_variant=body.min_accounts_per_variant,
        )
    )


@router.post("/experiments/{experiment_id}/{action}")
def experiment_action(
    experiment_id: str, action: str, p: Principal = Depends(admin_principal), db: Session = DB
) -> dict[str, Any]:
    if action not in ("start", "stop"):
        raise ValidationFailed("action must be start or stop")
    return experiments.as_dict(experiments.transition(db, p, experiment_id, action))
