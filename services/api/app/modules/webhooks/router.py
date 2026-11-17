from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.organisations.deps import TenantContext, require
from app.modules.webhooks import service
from app.modules.webhooks.models import WebhookDelivery, WebhookSubscription

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422)
}


def _people_admin(
    ctx: Annotated[TenantContext, Depends(require("member:manage"))],
) -> TenantContext:
    if ctx.scopes is not None:
        raise AppError(403, "forbidden", "Webhooks are managed by people, not API keys.")
    return ctx


CanManage = Annotated[TenantContext, Depends(_people_admin)]


class WebhookIn(BaseModel):
    url: Annotated[str, Field(min_length=8, max_length=500)]
    event_kinds: Annotated[list[str], Field(min_length=1)]
    description: Annotated[str, Field(max_length=200)] = ""


class WebhookOut(BaseModel):
    id: UUID
    url: str
    description: str
    event_kinds: list[str]
    created_by_user_id: UUID
    created_at: datetime
    disabled_at: datetime | None


class CreatedWebhookOut(WebhookOut):
    secret: str = Field(description="Signing secret. Shown once; store it now.")


class DeliveryOut(BaseModel):
    id: UUID
    subscription_id: UUID
    event_id: UUID | None
    event_kind: str
    status: str
    attempts: int
    last_status_code: int | None
    last_error: str | None
    last_response: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


def _out(subscription: WebhookSubscription) -> WebhookOut:
    return WebhookOut.model_validate(subscription, from_attributes=True)


def _delivery_out(delivery: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut.model_validate(delivery, from_attributes=True)


def _audit(
    request: Request,
    session: SessionDep,
    ctx: TenantContext,
    action: str,
    target: UUID,
    detail: dict[str, Any],
) -> None:
    audit.record(
        session,
        action,
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="webhook",
        target_id=str(target),
        ip_address=client_ip(request),
        detail=detail,
    )


@router.get("/events")
def event_kinds() -> list[str]:
    """The events a webhook can subscribe to."""
    return list(service.EVENT_KINDS)


@router.post("", status_code=201, responses=_ERRORS)
def create_webhook(
    body: WebhookIn, request: Request, session: SessionDep, ctx: CanManage
) -> CreatedWebhookOut:
    """Subscribe an endpoint to events. Administrators only. The signing secret is in this
    answer only."""
    subscription, secret = service.create_subscription(
        session, ctx, url=body.url, event_kinds=body.event_kinds, description=body.description
    )
    _audit(
        request,
        session,
        ctx,
        "webhook.created",
        subscription.id,
        {"url": subscription.url, "events": subscription.event_kinds},
    )
    return CreatedWebhookOut.model_validate({**_out(subscription).model_dump(), "secret": secret})


@router.get("", responses=_ERRORS)
def list_webhooks(session: SessionDep, ctx: CanManage) -> list[WebhookOut]:
    return [_out(s) for s in service.list_subscriptions(session, ctx)]


@router.delete("/{subscription_id}", status_code=204, responses=_ERRORS)
def disable_webhook(
    subscription_id: UUID, request: Request, session: SessionDep, ctx: CanManage
) -> None:
    """Turn a webhook off. Pending deliveries stop; the delivery log is kept."""
    subscription = service.get_subscription(session, ctx, subscription_id)
    service.disable(subscription)
    _audit(request, session, ctx, "webhook.disabled", subscription.id, {"url": subscription.url})


@router.post("/{subscription_id}/test", status_code=202, responses=_ERRORS)
def test_webhook(subscription_id: UUID, session: SessionDep, ctx: CanManage) -> DeliveryOut:
    """Send a signed `ping` event to the endpoint."""
    subscription = service.get_subscription(session, ctx, subscription_id)
    if subscription.disabled_at is not None:
        raise AppError(409, "webhook_disabled", "This webhook is turned off.")
    return _delivery_out(service.send_test(session, subscription))


@router.get("/{subscription_id}/deliveries", responses=_ERRORS)
def list_deliveries(
    subscription_id: UUID, session: SessionDep, ctx: CanManage
) -> list[DeliveryOut]:
    """The 50 newest deliveries, newest first."""
    subscription = service.get_subscription(session, ctx, subscription_id)
    return [_delivery_out(d) for d in service.list_deliveries(session, subscription)]


@router.get("/deliveries/failed", responses=_ERRORS)
def list_failed_deliveries(session: SessionDep, ctx: CanManage) -> list[DeliveryOut]:
    """Dead letters: the 100 newest deliveries, across all webhooks, that used up their attempts."""
    return [_delivery_out(d) for d in service.list_failed_deliveries(session, ctx)]


@router.post("/deliveries/{delivery_id}/redeliver", status_code=202, responses=_ERRORS)
def redeliver(
    delivery_id: UUID, request: Request, session: SessionDep, ctx: CanManage
) -> DeliveryOut:
    """Send a finished delivery again with the same body and a fresh set of attempts."""
    delivery = service.redeliver(session, service.get_delivery(session, ctx, delivery_id))
    _audit(
        request,
        session,
        ctx,
        "webhook.redelivered",
        delivery.subscription_id,
        {"delivery_id": str(delivery.id)},
    )
    return _delivery_out(delivery)
