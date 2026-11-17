"""One error envelope for every API failure (INSTRUCTIONS.md section 8)."""

import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Client-supplied IDs are echoed into logs and headers, so only a safe shape is accepted.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
}


class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    error: ErrorBody


class AppError(Exception):
    """Raise from services and routers for an expected, client-visible failure."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[ErrorDetail] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.headers = headers or {}


def _envelope(
    status_code: int, code: str, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, request_id=request_id_var.get(), details=details or []
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def install_error_handling(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        response = _envelope(exc.status_code, exc.code, exc.message, exc.details)
        response.headers.update(exc.headers)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        response = _envelope(exc.status_code, code, str(exc.detail))
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(field=".".join(str(part) for part in err["loc"]), message=err["msg"])
            for err in exc.errors()
        ]
        return _envelope(422, "validation_error", "Request validation failed.", details)

    @app.middleware("http")
    async def _request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if _SAFE_REQUEST_ID.match(supplied) else str(uuid.uuid4())
        request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Full detail goes to the log only; the client never sees internals.
            logger.exception("unhandled error")
            response = _envelope(500, "internal_error", "An unexpected error occurred.")
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response
