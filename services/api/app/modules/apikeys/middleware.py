"""Request middleware for the public API: the usage log of API keys, and idempotency keys.

Both write in their own short transaction (not the request's), so a record is kept even
when the request fails, and an answer is stored only after it has been sent back.
"""

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.db import get_engine
from app.core.logging import request_id_var
from app.modules.apikeys.models import ApiKeyUsage, IdempotencyRecord
from app.modules.auth.deps import SESSION_COOKIE

IDEMPOTENCY_HEADER = "Idempotency-Key"
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# A key may be reused for a different request after this long.
KEEP_FOR = timedelta(hours=24)
MAX_KEY_LENGTH = 200

CallNext = Callable[[Request], Awaitable[Response]]


def _error(status: int, code: str, message: str) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request_id_var.get(),
        "details": [],
    }
    return JSONResponse(status_code=status, content={"error": error})


def _log_usage(key_id: UUID, organisation_id: UUID, request: Request, status: int) -> None:
    with Session(get_engine()) as session:
        session.add(
            ApiKeyUsage(
                api_key_id=key_id,
                organisation_id=organisation_id,
                at=datetime.now(UTC),
                method=request.method,
                path=request.url.path[:300],
                status_code=status,
                request_id=request_id_var.get(),
                ip_address=request.client.host if request.client else None,
            )
        )
        session.commit()


def _claim(
    principal: str, key: str, request: Request, request_hash: str
) -> IdempotencyRecord | None:
    """Insert a fresh record and return None, or return the record already there."""
    with Session(get_engine(), expire_on_commit=False) as session:
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.principal == principal,
                IdempotencyRecord.key == key,
                IdempotencyRecord.created_at < datetime.now(UTC) - KEEP_FOR,
            )
        )
        session.add(
            IdempotencyRecord(
                principal=principal,
                key=key,
                method=request.method,
                path=request.url.path[:300],
                request_hash=request_hash,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return session.scalars(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.principal == principal, IdempotencyRecord.key == key
                )
            ).one()
    return None


def _store(principal: str, key: str, status: int, body: bytes, media_type: str | None) -> None:
    with Session(get_engine()) as session:
        record = session.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.principal == principal, IdempotencyRecord.key == key
            )
        ).one()
        if status >= 500:
            session.delete(record)  # a server error is not an answer; let the client try again
        else:
            record.status_code = status
            record.response = {"body": body.decode(), "media_type": media_type}
        session.commit()


def _replay(record: IdempotencyRecord) -> Response:
    stored: dict[str, Any] = record.response or {}
    response = Response(
        content=stored.get("body", ""),
        status_code=record.status_code or 200,
        media_type=stored.get("media_type"),
    )
    response.headers["Idempotent-Replayed"] = "true"
    return response


async def _idempotent(request: Request, call_next: CallNext) -> Response:
    key = request.headers.get(IDEMPOTENCY_HEADER)
    credential = request.headers.get("authorization") or request.cookies.get(SESSION_COOKIE)
    if key is None or request.method not in WRITE_METHODS or credential is None:
        return await call_next(request)
    if not key or len(key) > MAX_KEY_LENGTH:
        return _error(422, "validation_error", f"{IDEMPOTENCY_HEADER} must be 1 to 200 characters.")

    principal = hashlib.sha256(credential.encode()).hexdigest()
    body = await request.body()
    request_hash = hashlib.sha256(
        b"\n".join([request.method.encode(), str(request.url).encode(), body])
    ).hexdigest()
    existing = await run_in_threadpool(_claim, principal, key, request, request_hash)
    if existing is not None:
        if existing.request_hash != request_hash:
            return _error(
                422,
                "idempotency_key_reused",
                "This Idempotency-Key was used for a different request.",
            )
        if existing.status_code is None:
            return _error(
                409, "idempotency_in_progress", "The first request with this key is still running."
            )
        return _replay(existing)

    response = await call_next(request)
    chunks = [chunk async for chunk in response.body_iterator]  # type: ignore[attr-defined]
    content = b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)
    await run_in_threadpool(
        _store, principal, key, response.status_code, content, response.media_type
    )
    return Response(
        content=content,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def _public_api(request: Request, call_next: CallNext) -> Response:
        response = await _idempotent(request, call_next)
        api_key = getattr(request.state, "api_key", None)
        if api_key is not None:
            await run_in_threadpool(
                _log_usage, api_key[0], api_key[1], request, response.status_code
            )
        return response
