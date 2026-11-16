import os

# Tests need a reachable Postgres (docker compose locally, a service container in CI).
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://mls:mls@localhost:5432/mls")
os.environ.setdefault("ENVIRONMENT", "test")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
