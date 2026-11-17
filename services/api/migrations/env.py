from logging.config import fileConfig

from alembic import context
from sqlalchemy import func, select

import app.main  # noqa: F401  # importing the app registers every module's models on Base
from app.core.config import get_settings
from app.core.db import STARTUP_LOCK, Base, get_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=str(get_settings().database_url),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            connection.execute(select(func.pg_advisory_xact_lock(STARTUP_LOCK)))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
