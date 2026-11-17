from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.core.db import SessionDep
from app.core.errors import ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.listings.schemas import Money
from app.modules.organisations.deps import TenantContext, require
from app.modules.valuation import service
from app.modules.valuation.models import Valuation
from app.modules.valuation.schemas import (
    EvaluationOut,
    Outcome,
    Parameters,
    ValuationOut,
    ValuationRequest,
    ValuationResult,
)

listing_valuations_router = APIRouter(
    prefix="/listings/{listing_id}/valuations", tags=["valuation"]
)
valuations_router = APIRouter(prefix="/valuations", tags=["valuation"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422)
}

CanRead = Annotated[TenantContext, Depends(require("listing:read"))]


def valuation_out(valuation: Valuation) -> ValuationOut:
    outcome = None
    if valuation.outcome_price is not None and valuation.outcome_at is not None:
        outcome = Outcome(
            price=Money(amount=valuation.outcome_price, currency=valuation.result["currency"]),
            at=valuation.outcome_at,
            error_pct=service.error_pct(valuation),
            within_range=service.within_range(valuation),
        )
    return ValuationOut(
        id=valuation.id,
        listing_id=valuation.listing_id,
        status=valuation.status,
        model_version=valuation.model_version,
        simulation_version=valuation.simulation_version,
        parameters=Parameters.model_validate(valuation.parameters),
        result=ValuationResult.model_validate(valuation.result),
        outcome=outcome,
        requested_by_user_id=valuation.requested_by_user_id,
        created_at=valuation.created_at,
    )


@listing_valuations_router.post("", status_code=201, responses=_ERRORS)
def request_valuation(
    listing_id: UUID,
    body: ValuationRequest,
    request: Request,
    session: SessionDep,
    ctx: CanRead,
) -> ValuationOut:
    """Estimate a range from comparable reported sales. Not an appraisal. Only the
    organisation that owns the listing may ask; another organisation gets 404."""
    valuation = service.request_valuation(session, ctx, listing_id, body)
    audit.record(
        session,
        "valuation.requested",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="listing",
        target_id=str(listing_id),
        ip_address=client_ip(request),
        detail={
            "valuation_id": str(valuation.id),
            "status": valuation.status,
            "model_version": valuation.model_version,
            "simulation_version": valuation.simulation_version,
            "seed": valuation.parameters["seed"],
        },
    )
    return valuation_out(valuation)


@listing_valuations_router.get("", responses=_ERRORS)
def list_valuations(listing_id: UUID, session: SessionDep, ctx: CanRead) -> list[ValuationOut]:
    """The 20 newest valuations of a listing, newest first."""
    return [valuation_out(v) for v in service.list_valuations(session, ctx, listing_id)]


@valuations_router.get("/evaluation", responses=_ERRORS)
def evaluation(session: SessionDep, ctx: CanRead) -> list[EvaluationOut]:
    """How earlier estimates compare with the prices listings later sold for, per model version."""
    return service.evaluation(session, ctx)
