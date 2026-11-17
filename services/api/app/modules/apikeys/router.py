from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse
from app.modules.apikeys import service
from app.modules.apikeys.models import ApiKey
from app.modules.audit import service as audit
from app.modules.auth.deps import client_ip
from app.modules.organisations.deps import TenantContext, require

router = APIRouter(prefix="/api-keys", tags=["api keys"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422)
}

CanManage = Annotated[TenantContext, Depends(require("member:manage"))]


class ApiKeyIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: Annotated[list[str], Field(min_length=1)]
    rate_limit_per_minute: Annotated[int, Field(ge=1, le=service.MAX_RATE_LIMIT)] = 60


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str
    scopes: list[str]
    rate_limit_per_minute: int
    created_by_user_id: UUID
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    requests_last_minute: int


class CreatedApiKeyOut(ApiKeyOut):
    key: str = Field(description="The full key. Shown once; store it now.")


def _out(session: SessionDep, key: ApiKey) -> dict[str, Any]:
    return {
        **{k: getattr(key, k) for k in ApiKeyOut.model_fields if k != "requests_last_minute"},
        "requests_last_minute": service.used_in_last_minute(session, key.id),
    }


def _audit(
    request: Request, session: SessionDep, ctx: TenantContext, action: str, key: ApiKey
) -> None:
    audit.record(
        session,
        action,
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="api_key",
        target_id=str(key.id),
        ip_address=client_ip(request),
        detail={"name": key.name, "prefix": key.prefix, "scopes": key.scopes},
    )


@router.post("", status_code=201, responses=_ERRORS)
def create_api_key(
    body: ApiKeyIn, request: Request, session: SessionDep, ctx: CanManage
) -> CreatedApiKeyOut:
    """Create a key that acts as you, limited to its scopes. Administrators only; not with
    an API key. The full key is in this answer only."""
    if ctx.scopes is not None:
        raise AppError(403, "forbidden", "An API key cannot create keys.")
    unknown = sorted(set(body.scopes) - set(service.SCOPES))
    if unknown:
        raise AppError(
            422,
            "validation_error",
            f"Unknown scope(s): {', '.join(unknown)}. Allowed: {', '.join(service.SCOPES)}.",
        )
    key, token = service.create_key(
        session,
        organisation_id=ctx.organisation_id,
        user=ctx.user,
        name=body.name.strip(),
        scopes=body.scopes,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    _audit(request, session, ctx, "api_key.created", key)
    return CreatedApiKeyOut.model_validate({**_out(session, key), "key": token})


@router.get("", responses=_ERRORS)
def list_api_keys(session: SessionDep, ctx: CanManage) -> list[ApiKeyOut]:
    """The organisation's keys, newest first, without their secrets."""
    return [
        ApiKeyOut.model_validate(_out(session, key))
        for key in service.list_keys(session, ctx.organisation_id)
    ]


@router.delete("/{key_id}", status_code=204, responses=_ERRORS)
def revoke_api_key(key_id: UUID, request: Request, session: SessionDep, ctx: CanManage) -> None:
    """Revoke a key at once. It cannot be used again."""
    key = service.get_key(session, ctx.organisation_id, key_id)
    service.revoke(key)
    _audit(request, session, ctx, "api_key.revoked", key)
