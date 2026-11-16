import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import SessionDep
from app.core.errors import AppError, ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health", responses={503: {"model": ErrorResponse}})
def health(session: SessionDep) -> HealthResponse:
    """Readiness check: the API is up and can reach its database."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.exception("database health check failed")
        raise AppError(503, "database_unavailable", "The database is not reachable.") from exc
    return HealthResponse(status="ok", database="ok")
