from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings

# Any fixed number. Migrations and the demo seed hold it, so containers starting at the same
# moment (serverless cold starts) run them one after another.
STARTUP_LOCK = 2_100_000_022


class Base(DeclarativeBase):
    """Every module's models inherit from this so Alembic sees one metadata."""


def one_of(column: str, values: tuple[str, ...]) -> str:
    """SQL for a CHECK constraint limiting a text column to fixed values (trusted input only)."""
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


@lru_cache
def get_engine() -> Engine:
    return create_engine(str(get_settings().database_url), pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error.

    A handler may call `session.commit()` early to keep a record (for example a
    failed-login audit event) before raising.
    """
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise


# scope="function": the commit runs before the response is sent, so a failed commit
# becomes an error response instead of a success the client should not have seen.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]
