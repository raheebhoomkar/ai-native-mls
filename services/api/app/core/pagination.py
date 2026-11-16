"""Cursor pagination shared by every collection endpoint.

A cursor is an opaque token holding the sort-key values of the last item on a page.
Routers take `PageParamsDep`, services call `paginate`, responses use `Page[T]`.
"""

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query
from pydantic import BaseModel
from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.core.errors import AppError, ErrorDetail

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class PageParams:
    limit: int
    cursor: dict[str, Any] | None


def _invalid_cursor() -> AppError:
    return AppError(
        400,
        "invalid_cursor",
        "The pagination cursor is not valid.",
        [ErrorDetail(field="query.cursor", message="Malformed cursor.")],
    )


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, default=str, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except ValueError:  # covers bad base64, bad UTF-8 and bad JSON
        values = None
    if not isinstance(values, dict):
        raise _invalid_cursor()
    return values


def _page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=decode_cursor(cursor) if cursor else None)


PageParamsDep = Annotated[PageParams, Depends(_page_params)]


def _to_cursor_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _from_cursor_value(column: InstrumentedAttribute[Any], raw: Any) -> Any:
    """Cursors come from the client, so values are parsed to the column's type."""
    python_type = column.type.python_type
    try:
        if python_type is datetime:
            return datetime.fromisoformat(raw)
        if python_type is UUID:
            return UUID(raw)
        if python_type is Decimal:
            return Decimal(raw)
    except (TypeError, ValueError, AttributeError, InvalidOperation):
        raise _invalid_cursor() from None
    if not isinstance(raw, python_type):
        raise _invalid_cursor()
    return raw


def paginate[T](
    session: Session,
    stmt: Select[T],
    page: PageParams,
    *,
    sort: InstrumentedAttribute[Any],
    id_column: InstrumentedAttribute[Any],
    descending: bool = True,
) -> tuple[Sequence[T], str | None]:
    """Keyset pagination over `(sort, id_column)`; `id_column` breaks ties and must be unique.

    `stmt` must select a single ORM entity that has both columns.
    """
    if page.cursor is not None:
        if set(page.cursor) != {"sort", "id"}:
            raise _invalid_cursor()
        last_sort = _from_cursor_value(sort, page.cursor["sort"])
        last_id = _from_cursor_value(id_column, page.cursor["id"])
        if descending:
            after = or_(sort < last_sort, and_(sort == last_sort, id_column < last_id))
        else:
            after = or_(sort > last_sort, and_(sort == last_sort, id_column > last_id))
        stmt = stmt.where(after)
    ordering = (sort.desc(), id_column.desc()) if descending else (sort.asc(), id_column.asc())
    rows = session.scalars(stmt.order_by(*ordering).limit(page.limit + 1)).all()
    if len(rows) <= page.limit:
        return rows, None
    rows = rows[: page.limit]
    last = rows[-1]
    next_cursor = encode_cursor(
        {
            "sort": _to_cursor_value(getattr(last, sort.key)),
            "id": _to_cursor_value(getattr(last, id_column.key)),
        }
    )
    return rows, next_cursor
