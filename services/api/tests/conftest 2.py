import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Tests run in their own database, "<configured name>_test", on the same Postgres server
# (docker compose locally, a service container in CI). The developer's data is never touched
# and never changes a test result. Set before the app is imported, which reads the setting.
_BASE_URL = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://mls:mls@localhost:5432/mls")
)
_TEST_URL = _BASE_URL.set(database=f"{_BASE_URL.database}_test")
os.environ["DATABASE_URL"] = _TEST_URL.render_as_string(hide_password=False)
os.environ.setdefault("ENVIRONMENT", "test")

from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import get_engine, get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.auth import service as auth  # noqa: E402
from app.modules.auth.models import User  # noqa: E402
from app.modules.organisations import service as organisations  # noqa: E402
from app.modules.organisations.models import Organisation  # noqa: E402

PASSWORD = "correct horse battery staple"  # test-only credential


@pytest.fixture(scope="session", autouse=True)
def _migrated_database() -> None:
    """Create the test database if needed and apply migrations, proving they run."""
    admin = create_engine(_BASE_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _TEST_URL.database}
        )
        if not exists:
            # The name comes from configuration, not user input; identifiers cannot be bound.
            connection.execute(text(f'CREATE DATABASE "{_TEST_URL.database}"'))
    admin.dispose()
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")


@pytest.fixture
def db() -> Iterator[Session]:
    """A session whose work is rolled back after the test, including commits made by the app."""
    connection = get_engine().connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def app(db: Session) -> FastAPI:
    application = create_app()

    def _session() -> Iterator[Session]:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

    application.dependency_overrides[get_session] = _session
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make(email: str, *, platform_admin: bool = False, name: str = "Test User") -> User:
        user = auth.create_user(
            db, email=email, full_name=name, password=PASSWORD, is_platform_admin=platform_admin
        )
        db.commit()
        return user

    return _make


@pytest.fixture
def make_org(db: Session) -> Callable[..., Organisation]:
    def _make(name: str, members: dict[User, str] | None = None) -> Organisation:
        organisation = organisations.create_organisation(db, name=name, kind="brokerage")
        for user, role in (members or {}).items():
            organisations.add_member(
                db, user_id=user.id, organisation_id=organisation.id, role=role
            )
        db.commit()
        return organisation

    return _make


@pytest.fixture
def login_as(app: FastAPI) -> Callable[[User], TestClient]:
    """A separate client (own cookie jar) signed in as the given user."""

    def _login(user: User) -> TestClient:
        test_client = TestClient(app)
        response = test_client.post(
            "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        return test_client

    return _login
