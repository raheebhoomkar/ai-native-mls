"""Cursor pagination shared by every collection endpoint.

A cursor is an opaque token holding the sort-key values of the last item on a page.
Routers take `PageParams`, services build the keyset query, responses use `Page[T]`.
"""

import base64
import json
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel

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
        raise AppError(
            400,
            "invalid_cursor",
            "The pagination cursor is not valid.",
            [ErrorDetail(field="query.cursor", message="Malformed cursor.")],
        )
    return values


def _page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=decode_cursor(cursor) if cursor else None)


PageParamsDep = Annotated[PageParams, Depends(_page_params)]
