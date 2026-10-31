from datetime import datetime, timezone
from unittest.mock import AsyncMock
from fastapi import FastAPI
import httpx
import pytest

from app.api.deps import get_mongo_repo, get_timescale_repo
from app.api.error_handlers import register_error_handlers
from app.api.v1.diagnostics import router as diagnostics_router
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.domain.models import (
    DiagnosticAlert,
    DiagnosticSeverity,
    GPSLocation,
    VehicleHealthStatus,
    VehicleTwinState,
)


@pytest.fixture
def mock_timescale_repo():
    repo = AsyncMock()
    repo.health_check = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def mock_mongo_repo():
    repo = AsyncMock()
    repo.health_check = AsyncMock(return_value=True)
    repo.get_vehicle_twin = AsyncMock(return_value=None)
    repo.get_recent_alerts = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def test_app(mock_timescale_repo, mock_mongo_repo):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(diagnostics_router)

    app.dependency_overrides[get_timescale_repo] = lambda: mock_timescale_repo
    app.dependency_overrides[get_mongo_repo] = lambda: mock_mongo_repo
    return app


@pytest.mark.asyncio
async def test_healthz_endpoint(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/healthz")
        assert res.status_code == 200
        assert res.json()["status"] == "UP"


@pytest.mark.asyncio
async def test_readyz_healthy(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/readyz")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "UP"
        assert data["components"]["timescaledb"] == "UP"
        assert data["components"]["mongodb"] == "UP"


@pytest.mark.asyncio
async def test_readyz_unhealthy(test_app: FastAPI, mock_timescale_repo):
    mock_timescale_repo.health_check = AsyncMock(return_value=False)

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/readyz")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "DOWN"
        assert data["components"]["timescaledb"] == "DOWN"


@pytest.mark.asyncio
async def test_get_diagnostics_not_found(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/iot/diagnostics/non-existent-id")
        assert res.status_code == 404
        assert res.headers["content-type"] == "application/problem+json"
        data = res.json()
        assert data["status"] == 404
        assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_get_diagnostics_success(test_app: FastAPI, mock_mongo_repo):
    twin = VehicleTwinState(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="vehicle-123",
        last_timestamp=datetime.now(timezone.utc),
        last_location=GPSLocation(latitude=-12.0464, longitude=-77.0428),
        last_speed_kmh=70.0,
        last_engine_rpm=2400,
        last_coolant_temp_c=92,
        last_battery_voltage=13.8,
        last_fuel_level_percent=80.0,
        active_dtcs=["P0171"],
        active_alerts=[
            DiagnosticAlert(
                tenant_id="00000000-0000-0000-0000-000000000001",
                vehicle_id="vehicle-123",
                code="P0171",
                severity=DiagnosticSeverity.WARNING,
                title="System Too Lean",
                description="Lean fuel trim",
            )
        ],
        overall_status=VehicleHealthStatus.WARNING,
    )
    mock_mongo_repo.get_vehicle_twin = AsyncMock(return_value=twin)

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/iot/diagnostics/vehicle-123", headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"})
        assert res.status_code == 200
        data = res.json()
        assert data["vehicle_id"] == "vehicle-123"
        assert data["overall_status"] == "WARNING"
        assert "P0171" in data["active_dtcs"]
        assert len(data["active_alerts"]) == 1


@pytest.mark.asyncio
async def test_metrics_endpoint(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/metrics")
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        body = res.text
        assert "iot_processor_messages_processed_total" in body
        assert "iot_processor_evaluation_latency_seconds" in body
        assert "iot_processor_timescale_insert_latency_seconds" in body
        assert "iot_processor_mongo_update_latency_seconds" in body
        assert "iot_processor_alerts_emitted_total" in body

