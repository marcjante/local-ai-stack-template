from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

os.environ.setdefault("HCPALAU_DATABASE_URL", "sqlite://")
os.environ.setdefault("HCPALAU_ADMIN_TOKEN", "test-admin-token")

from backend.app.database import engine  # noqa: E402
from backend.app.main import app  # noqa: E402


@pytest.fixture
def client():
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-admin-token"}
