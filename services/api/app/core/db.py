from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Every module's models inherit from this so Alembic sees one metadata."""


@lru_cache
def get_engine() -> Engine:
    return create_engine(str(get_settings().database_url), pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    with Session(get_engine()) as session, session.begin():
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
