"""API keys for third-party clients.

A key acts as the member who created it, in that member's organisation, with the member's
current permissions limited to the key's scopes. If the member leaves or loses a permission,
the key loses it too.
"""

import secrets
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.apikeys.middleware import KEEP_FOR
from app.modules.apikeys.models import ApiKey, ApiKeyUsage, IdempotencyRecord
from app.modules.auth.models import User
from app.modules.auth.service import hash_token
from app.modules.organisations import service as organisations

# What a key may be allowed to do. Member, audit and key management stay with people.
SCOPES: tuple[str, ...] = ("listing:read", "listing:write")
TOKEN_PREFIX = "mls_"  # noqa: S105  # a public marker, not a secret
MAX_RATE_LIMIT = 600


def _invalid() -> AppError:
    return AppError(401, "invalid_api_key", "The API key is not valid or has been revoked.")


def create_key(
    session: Session,
    *,
    organisation_id: UUID,
    user: User,
    name: str,
    scopes: Sequence[str],
    rate_limit_per_minute: int,
) -> tuple[ApiKey, str]:
    """Return the key row and the full key. The full key is never stored or shown again."""
    prefix = f"{TOKEN_PREFIX}{secrets.token_hex(4)}"
    token = f"{prefix}_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        organisation_id=organisation_id,
        created_by_user_id=user.id,
        name=name,
        prefix=prefix,
        key_hash=hash_token(token),
        scopes=sorted(set(scopes)),
        rate_limit_per_minute=rate_limit_per_minute,
    )
    session.add(key)
    session.flush()
    session.refresh(key)
    return key, token


def list_keys(session: Session, organisation_id: UUID) -> Sequence[ApiKey]:
    return session.scalars(
        select(ApiKey)
        .where(ApiKey.organisation_id == organisation_id)
        .order_by(ApiKey.created_at.desc())
    ).all()


def get_key(session: Session, organisation_id: UUID, key_id: UUID) -> ApiKey:
    key = session.get(ApiKey, key_id)
    if key is None or key.organisation_id != organisation_id:
        raise AppError(404, "not_found", "API key not found.")
    return key


def revoke(key: ApiKey) -> None:
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)


def used_in_last_minute(session: Session, key_id: UUID) -> int:
    since = datetime.now(UTC) - timedelta(minutes=1)
    return (
        session.scalar(
            select(func.count())
            .select_from(ApiKeyUsage)
            .where(ApiKeyUsage.api_key_id == key_id, ApiKeyUsage.at >= since)
        )
        or 0
    )


def delete_expired(session: Session, usage_before: datetime) -> dict[str, int]:
    """Remove idempotency records past their life and usage rows older than `usage_before`."""
    records = session.execute(
        delete(IdempotencyRecord).where(IdempotencyRecord.created_at < datetime.now(UTC) - KEEP_FOR)
    )
    usage = session.execute(delete(ApiKeyUsage).where(ApiKeyUsage.at < usage_before))
    return {
        "idempotency_records": int(getattr(records, "rowcount", 0) or 0),
        "api_key_usage": int(getattr(usage, "rowcount", 0) or 0),
    }


def authenticate(session: Session, token: str) -> tuple[ApiKey, User, str]:
    """Resolve a bearer token to its key, the member it acts as, and their role."""
    if not token.startswith(TOKEN_PREFIX):
        raise _invalid()
    key = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_token(token)))
    if key is None or key.revoked_at is not None:
        raise _invalid()
    role = next(
        (
            membership.role
            for membership, _ in organisations.list_memberships(session, key.created_by_user_id)
            if membership.organisation_id == key.organisation_id
        ),
        None,
    )
    if role is None:
        raise AppError(
            401, "invalid_api_key", "The member who created this key has left the organisation."
        )
    key.last_used_at = datetime.now(UTC)
    return key, session.get_one(User, key.created_by_user_id), role


def check_rate(session: Session, key: ApiKey) -> None:
    """Refuse once the key has made its allowed number of requests in the last minute.

    shortcut: counts requests already logged, so a burst of parallel requests can pass a few
    over the limit; move the counter into the database row or Redis if that matters.
    """
    if used_in_last_minute(session, key.id) >= key.rate_limit_per_minute:
        raise AppError(
            429,
            "rate_limited",
            f"This key allows {key.rate_limit_per_minute} requests a minute. Try again shortly.",
            headers={"Retry-After": "60"},
        )
