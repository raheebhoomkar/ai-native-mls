"""Webhooks: an organisation's endpoints get its outbox events, signed, with retries.

    outbox event -> `webhooks.fanout` job -> one delivery row per matching subscription
                 -> `webhooks.deliver` job per attempt

A delivery job never raises: it records the attempt on the delivery row and, if the
endpoint failed, queues the next attempt itself (30 s, 1 min, 2 min, 4 min, 8 min).
Events are thin: they say what changed; the receiver reads the details through the API.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.organisations.deps import TenantContext
from app.modules.outbox import service as outbox
from app.modules.outbox.models import OutboxEvent
from app.modules.webhooks.models import WebhookDelivery, WebhookSubscription

EVENT_KINDS: tuple[str, ...] = ("listing.changed", "property.changed", "workflow.finished")
MAX_ATTEMPTS = 6
BACKOFF = timedelta(seconds=30)
TIMEOUT_SECONDS = 10.0
SIGNATURE_HEADER = "X-MLS-Signature"
# A receiver should refuse a signature older than this (replay protection).
TOLERANCE_SECONDS = 300

for _kind in EVENT_KINDS:
    outbox.subscribe(_kind, "webhooks.fanout")

# (url, body, headers, timeout) -> (status code, start of the response body)
Sender = Callable[[str, bytes, dict[str, str], float], tuple[int, str]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect could point anywhere, including inside our network; treat it as a failure."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def urllib_send(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read(500).decode(errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read(500).decode(errors="replace")


def get_sender() -> Sender:
    return urllib_send


# --- Signing ---------------------------------------------------------------------------------


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """`t=<unix time>,v1=<hex HMAC-SHA256 of "<t>." + body>`."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def verify(secret: str, header: str, body: bytes, now: float | None = None) -> bool:
    """What a receiver does: check the signature and that it is recent. Kept here so the
    developer guide's recipe is tested."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
    except KeyError, ValueError:
        return False
    if abs((now or time.time()) - timestamp) > TOLERANCE_SECONDS:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), header)


# --- Where we may send -----------------------------------------------------------------------


def check_url(url: str) -> None:
    """Refuse URLs that would let a subscriber reach inside our own network.

    Outside production, http and local addresses are allowed so a developer can point a
    subscription at a receiver on their machine.
    """
    parts = urlsplit(url)
    production = get_settings().environment == "production"
    allowed = ("https",) if production else ("https", "http")
    if parts.scheme not in allowed or not parts.hostname:
        raise _bad_url("Use an https:// address." if production else "Use an http(s):// address.")
    if not production:
        return
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError:
        raise _bad_url("The address could not be resolved.") from None
    for address in addresses:
        ip = ipaddress.ip_address(str(address).split("%")[0])
        if not ip.is_global:
            raise _bad_url("The address points to a private or reserved network.")


def _bad_url(message: str) -> AppError:
    return AppError(422, "webhook_url_not_allowed", message)


# --- Subscriptions ---------------------------------------------------------------------------


def create_subscription(
    session: Session,
    ctx: TenantContext,
    *,
    url: str,
    event_kinds: Sequence[str],
    description: str,
) -> tuple[WebhookSubscription, str]:
    unknown = sorted(set(event_kinds) - set(EVENT_KINDS))
    if unknown:
        raise AppError(
            422,
            "validation_error",
            f"Unknown event(s): {', '.join(unknown)}. Allowed: {', '.join(EVENT_KINDS)}.",
        )
    check_url(url)
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    subscription = WebhookSubscription(
        organisation_id=ctx.organisation_id,
        created_by_user_id=ctx.user.id,
        url=url,
        description=description,
        event_kinds=sorted(set(event_kinds)),
        secret=secret,
    )
    session.add(subscription)
    session.flush()
    session.refresh(subscription)
    return subscription, secret


def list_subscriptions(session: Session, ctx: TenantContext) -> Sequence[WebhookSubscription]:
    return session.scalars(
        select(WebhookSubscription)
        .where(WebhookSubscription.organisation_id == ctx.organisation_id)
        .order_by(WebhookSubscription.created_at.desc())
    ).all()


def get_subscription(
    session: Session, ctx: TenantContext, subscription_id: UUID
) -> WebhookSubscription:
    subscription = session.get(WebhookSubscription, subscription_id)
    if subscription is None or subscription.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Webhook not found.")
    return subscription


def disable(subscription: WebhookSubscription) -> None:
    if subscription.disabled_at is None:
        subscription.disabled_at = datetime.now(UTC)


def list_deliveries(
    session: Session, subscription: WebhookSubscription
) -> Sequence[WebhookDelivery]:
    return session.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.subscription_id == subscription.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(50)
    ).all()


def list_failed_deliveries(session: Session, ctx: TenantContext) -> Sequence[WebhookDelivery]:
    """The organisation's 100 newest deliveries that used up their attempts: the dead letters."""
    return session.scalars(
        select(WebhookDelivery)
        .join(WebhookSubscription)
        .where(
            WebhookSubscription.organisation_id == ctx.organisation_id,
            WebhookDelivery.status == "failed",
        )
        .order_by(WebhookDelivery.created_at.desc())
        .limit(100)
    ).all()


def counts(session: Session, since: datetime) -> dict[str, int]:
    """Platform-wide delivery counts for monitoring."""
    row = session.execute(
        select(
            func.count().filter(WebhookDelivery.status == "pending"),
            func.count().filter(
                WebhookDelivery.status == "failed", WebhookDelivery.created_at >= since
            ),
        )
    ).one()
    return dict(zip(("pending", "failed_recently"), row, strict=True))


def get_delivery(session: Session, ctx: TenantContext, delivery_id: UUID) -> WebhookDelivery:
    delivery = session.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise AppError(404, "not_found", "Delivery not found.")
    get_subscription(session, ctx, delivery.subscription_id)  # 404 for other organisations
    return delivery


# --- Deliveries ------------------------------------------------------------------------------


def _body(event_id: UUID | None, kind: str, organisation_id: UUID, data: dict[str, Any]) -> str:
    return json.dumps(
        {
            "id": str(event_id) if event_id else None,
            "type": kind,
            "created_at": datetime.now(UTC).isoformat(),
            "organisation_id": str(organisation_id),
            "data": data,
        },
        sort_keys=True,
    )


def _queue(
    session: Session,
    delivery: WebhookDelivery,
    organisation_id: UUID,
    delay: timedelta | None = None,
) -> None:
    delivery.next_attempt_at = datetime.now(UTC) + (delay or timedelta(0))
    jobs.enqueue(
        session,
        "webhooks.deliver",
        {"delivery_id": str(delivery.id)},
        organisation_id=organisation_id,
        max_attempts=1,  # retries are ours: each attempt is recorded on the delivery
        delay=delay,
    )


def _new_delivery(
    session: Session, subscription: WebhookSubscription, event_id: UUID | None, kind: str, body: str
) -> WebhookDelivery:
    delivery = WebhookDelivery(
        subscription_id=subscription.id,
        event_id=event_id,
        event_kind=kind,
        body=body,
        created_at=datetime.now(UTC),
    )
    session.add(delivery)
    session.flush()
    _queue(session, delivery, subscription.organisation_id)
    return delivery


@jobs.handler("webhooks.fanout")
def fanout(session: Session, job: Job) -> None:
    """Idempotent: a subscription that already has a delivery for the event is skipped."""
    event = session.get(OutboxEvent, UUID(job.payload["event_id"]))
    if event is None:
        return
    subscriptions = session.scalars(
        select(WebhookSubscription).where(
            WebhookSubscription.organisation_id == event.organisation_id,
            WebhookSubscription.disabled_at.is_(None),
        )
    ).all()
    for subscription in subscriptions:
        if event.kind not in subscription.event_kinds:
            continue
        exists = session.scalar(
            select(WebhookDelivery.id).where(
                WebhookDelivery.subscription_id == subscription.id,
                WebhookDelivery.event_id == event.id,
            )
        )
        if exists is None:
            data = {
                "subject_type": event.subject_type,
                "subject_id": str(event.subject_id),
                **event.payload,
            }
            _new_delivery(
                session,
                subscription,
                event.id,
                event.kind,
                _body(event.id, event.kind, event.organisation_id, data),
            )


def send_test(session: Session, subscription: WebhookSubscription) -> WebhookDelivery:
    """A `ping` event, to check the endpoint and its signature check."""
    body = _body(
        None, "ping", subscription.organisation_id, {"subscription_id": str(subscription.id)}
    )
    return _new_delivery(session, subscription, None, "ping", body)


def redeliver(session: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """Send a finished delivery again, with a fresh set of attempts and the same body."""
    if delivery.status == "pending":
        raise AppError(409, "delivery_pending", "This delivery is still being tried.")
    subscription = session.get_one(WebhookSubscription, delivery.subscription_id)
    if subscription.disabled_at is not None:
        raise AppError(409, "webhook_disabled", "This webhook is turned off.")
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.delivered_at = None
    _queue(session, delivery, subscription.organisation_id)
    return delivery


@jobs.handler("webhooks.deliver")
def deliver(session: Session, job: Job) -> None:
    delivery = session.get(WebhookDelivery, UUID(job.payload["delivery_id"]), with_for_update=True)
    if delivery is None or delivery.status != "pending":
        return
    subscription = session.get_one(WebhookSubscription, delivery.subscription_id)
    if subscription.disabled_at is not None:
        delivery.status = "failed"
        delivery.last_error = "The webhook was turned off."
        delivery.next_attempt_at = None
        return

    delivery.attempts += 1
    body = delivery.body.encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "AI-Native-MLS-Webhooks/1",
        "X-MLS-Event": delivery.event_kind,
        "X-MLS-Delivery": str(delivery.id),
        SIGNATURE_HEADER: sign(subscription.secret, int(time.time()), body),
    }
    error: str | None = None
    try:
        check_url(subscription.url)  # again: DNS may point elsewhere now
        status, text = get_sender()(subscription.url, body, headers, TIMEOUT_SECONDS)
        delivery.last_status_code, delivery.last_response = status, text[:500]
        if not 200 <= status < 300:
            error = f"The endpoint answered HTTP {status}."
    except AppError as refused:
        error = refused.message
    except (OSError, ValueError) as failure:  # timeouts, refused connections, bad URLs
        error = f"{type(failure).__name__}: {failure}"[:1000]

    delivery.last_error = error
    if error is None:
        delivery.status = "succeeded"
        delivery.delivered_at = datetime.now(UTC)
        delivery.next_attempt_at = None
    elif delivery.attempts >= MAX_ATTEMPTS:
        delivery.status = "failed"
        delivery.next_attempt_at = None
    else:
        _queue(
            session, delivery, subscription.organisation_id, BACKOFF * 2 ** (delivery.attempts - 1)
        )
