from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.ai.models import AgentRun
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.auth.models import User
from app.modules.compliance import service
from app.modules.compliance.schemas import (
    AppealDecisionIn,
    AppealIn,
    ComplianceDecisionOut,
    ComplianceQueueItemOut,
    ComplianceScan,
    ComplianceScanOut,
    FindingDecisionIn,
    FindingReviewOut,
)
from app.modules.listings.models import Listing
from app.modules.organisations.deps import TenantContext, require
from app.modules.review.models import ReviewDecision

listing_scans_router = APIRouter(
    prefix="/listings/{listing_id}/compliance/scans", tags=["compliance"]
)
compliance_router = APIRouter(prefix="/compliance", tags=["compliance"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]
CanWrite = Annotated[TenantContext, Depends(require("listing:write"))]
CanPublish = Annotated[TenantContext, Depends(require("listing:publish"))]


def _names(session: Session, reviews: list[service.FindingReview]) -> dict[UUID, str]:
    ids = {
        row.decided_by_user_id
        for item in reviews
        for row in (item.decision, item.appeal, item.appeal_decision)
        if row
    }
    if not ids:
        return {}
    return dict(session.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _decision_out(row: ReviewDecision, names: dict[UUID, str]) -> ComplianceDecisionOut:
    return ComplianceDecisionOut(
        decision=row.decision,
        note=row.note,
        decided_by_user_id=row.decided_by_user_id,
        decided_by_name=names.get(row.decided_by_user_id, ""),
        decided_at=row.decided_at,
    )


def _review_out(item: service.FindingReview, names: dict[UUID, str]) -> FindingReviewOut:
    def out(row: ReviewDecision | None) -> ComplianceDecisionOut | None:
        return _decision_out(row, names) if row else None

    return FindingReviewOut(
        state=item.state,
        decision=out(item.decision),
        appeal=out(item.appeal),
        appeal_decision=out(item.appeal_decision),
    )


def scan_out(
    session: Session, ctx: TenantContext, run: AgentRun, listing: Listing
) -> ComplianceScanOut:
    task, reviews = service.review_of(session, run)
    names = _names(session, reviews)
    stalled = service.stalled(session, run)
    return ComplianceScanOut(
        id=run.id,
        listing_id=run.listing_id,
        status="failed" if stalled else run.status,
        listing_version=run.inputs[0]["listing_version"],
        checked_title=run.inputs[0]["title"],
        checked_remarks=run.inputs[0]["remarks"],
        provider=run.provider,
        model=run.model,
        model_version=run.model_version,
        output=ComplianceScan.model_validate(run.output) if run.output is not None else None,
        error=stalled or run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        is_demo=run.provider == "demo",
        reviews=[_review_out(item, names) for item in reviews],
        review_open=task is not None and task.status == "open",
        can_review=service.can_review(ctx, listing),
        can_appeal=service.can_appeal(ctx, listing),
    )


def _record(
    session: Session, ctx: TenantContext, request: Request, action: str, decided: service.Decided
) -> ComplianceDecisionOut:
    """Audit a decision and return it."""
    run, finding, row = decided
    session.refresh(row)  # server-set decided_at
    audit.record(
        session,
        action,
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run.id),
        ip_address=client_ip(request),
        detail={
            "listing_id": str(run.listing_id),
            "item": row.item_key,
            "rule_id": finding.rule_id,
            "policy_id": run.inputs[0]["policy_id"],
            "policy_version": run.inputs[0]["policy_version"],
            "decision": row.decision,
        },
    )
    return _decision_out(row, {ctx.user.id: ctx.user.full_name})


@listing_scans_router.post("", status_code=202, responses=_ERRORS)
def request_scan(
    listing_id: UUID, request: Request, ctx: CanWrite, session: SessionDep
) -> ComplianceScanOut:
    """Check the listing's title and remarks against the listing policy. Poll the list until
    the scan finishes. Findings are for a person to review; the listing is never changed.
    """
    listing, run = service.request_scan(session, ctx, listing_id)
    service.record_requested(session, ctx, run, client_ip(request))
    session.refresh(run)  # server-set created_at
    return scan_out(session, ctx, run, listing)


@listing_scans_router.get("", responses=_ERRORS)
def list_scans(listing_id: UUID, ctx: CanRead, session: SessionDep) -> list[ComplianceScanOut]:
    """Newest first. Only the organisation that owns the listing sees them."""
    listing, runs = service.list_scans(session, ctx, listing_id)
    return [scan_out(session, ctx, run, listing) for run in runs]


@compliance_router.post(
    "/scans/{run_id}/findings/{index}/decision", status_code=201, responses=_ERRORS
)
def decide_finding(
    run_id: UUID,
    index: int,
    body: FindingDecisionIn,
    request: Request,
    ctx: CanPublish,
    session: SessionDep,
) -> ComplianceDecisionOut:
    """Accept (a real problem), dismiss (not a problem) or ask for edits (note required).
    Final; a disputed decision goes to appeal. The listing itself is never changed.
    """
    decided = service.decide_finding(
        session, ctx, run_id, index, decision=body.decision, note=body.note
    )
    return _record(session, ctx, request, "compliance.finding_decided", decided)


@compliance_router.post(
    "/scans/{run_id}/findings/{index}/appeal", status_code=201, responses=_ERRORS
)
def appeal(
    run_id: UUID, index: int, body: AppealIn, request: Request, ctx: CanWrite, session: SessionDep
) -> ComplianceDecisionOut:
    """The listing's agent disputes an accepted finding or a request for edits, once."""
    decided = service.appeal(session, ctx, run_id, index, reason=body.reason)
    return _record(session, ctx, request, "compliance.finding_appealed", decided)


@compliance_router.post(
    "/scans/{run_id}/findings/{index}/appeal/decision", status_code=201, responses=_ERRORS
)
def decide_appeal(
    run_id: UUID,
    index: int,
    body: AppealDecisionIn,
    request: Request,
    ctx: CanPublish,
    session: SessionDep,
) -> ComplianceDecisionOut:
    """Uphold or overturn the first decision. Someone other than the first reviewer rules."""
    decided = service.decide_appeal(
        session, ctx, run_id, index, decision=body.decision, note=body.note
    )
    return _record(session, ctx, request, "compliance.appeal_decided", decided)


@compliance_router.get("/queue", responses=_ERRORS)
def review_queue(ctx: CanPublish, session: SessionDep) -> list[ComplianceQueueItemOut]:
    """Findings waiting for a reviewer in this organisation, oldest first. Listings whose
    agent is you are left out: someone else reviews them.
    """
    items = service.queue(session, ctx)
    names = _names(session, [item.review for item in items])
    return [
        ComplianceQueueItemOut(
            scan_id=item.run.id,
            listing_id=item.listing.id,
            listing_title=item.listing.title,
            finding_index=item.index,
            finding=item.finding,
            state="appealed" if item.review.state == "appealed" else "open",
            review=_review_out(item.review, names),
            policy_version=item.run.inputs[0]["policy_version"],
            waiting_since=item.waiting_since,
        )
        for item in items
    ]
