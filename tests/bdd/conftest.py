import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def api_client() -> TestClient:
    """Provide a FastAPI TestClient for BDD REST acceptance scenarios."""
    return TestClient(app)


@pytest.fixture
def bdd_context() -> dict:
    """Shared mutable scenario context storing headers, tokens, and last response."""
    return {"headers": {"Content-Type": "application/json"}, "last_response": None}
