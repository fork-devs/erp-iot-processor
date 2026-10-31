from datetime import datetime, timezone
from unittest.mock import AsyncMock
from fastapi import FastAPI
import httpx
import pytest

from app.api.deps import get_mongo_repo, get_timescale_repo
from app.api.error_handlers import register_error_handlers
from app.api.v1.telemetry_queries import router as telemetry_queries_router
from app.domain.models import DiagnosticAlert, DiagnosticSeverity


@pytest.fixture
def mock_timescale_repo():
    repo = AsyncMock()
    now = datetime.now(timezone.utc)
    repo.get_vehicle_snapshots = AsyncMock(
        return_value=[
            {
                "time": now,
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "vehicle_id": "11111111-1111-1111-1111-111111111111",
                "device_id": "OBD-01",
                "speed_kmh": 65.5,
                "engine_rpm": 2200,
                "coolant_temp_c": 90,
                "battery_voltage": 13.8,
                "fuel_level_percent": 55.0,
            }
        ]
    )
    return repo


@pytest.fixture
def mock_mongo_repo():
    repo = AsyncMock()
    now = datetime.now(timezone.utc)
    repo.get_paginated_alerts = AsyncMock(
        return_value=[
            DiagnosticAlert(
                id="alert-1",
                tenant_id="00000000-0000-0000-0000-000000000001",
                vehicle_id="11111111-1111-1111-1111-111111111111",
                timestamp=now,
                code="P0300",
                severity=DiagnosticSeverity.CRITICAL,
                title="Misfire Detected",
                description="Random cylinder misfire",
            )
        ]
    )
    return repo


@pytest.fixture
def test_app(mock_timescale_repo, mock_mongo_repo):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(telemetry_queries_router, prefix="/api/v1/vehicles")
    app.include_router(telemetry_queries_router, prefix="/api/v1/iot/vehicles")

    app.dependency_overrides[get_timescale_repo] = lambda: mock_timescale_repo
    app.dependency_overrides[get_mongo_repo] = lambda: mock_mongo_repo
    return app


@pytest.mark.asyncio
async def test_get_telemetry_snapshots_success(test_app: FastAPI, mock_timescale_repo):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/vehicles/11111111-1111-1111-1111-111111111111/telemetry-snapshots?page=0&size=20",
            headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["vehicle_id"] == "11111111-1111-1111-1111-111111111111"
        assert data[0]["speed_kmh"] == 65.5
        assert data[0]["engine_rpm"] == 2200

        mock_timescale_repo.get_vehicle_snapshots.assert_awaited_with(
            tenant_id="00000000-0000-0000-0000-000000000001",
            vehicle_id="11111111-1111-1111-1111-111111111111",
            page=0,
            size=20,
        )


@pytest.mark.asyncio
async def test_get_telemetry_snapshots_dual_route(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/iot/vehicles/11111111-1111-1111-1111-111111111111/telemetry-snapshots")
        assert res.status_code == 200
        assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_get_telemetry_snapshots_invalid_pagination(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Negative page
        res = await client.get("/api/v1/vehicles/11111111-1111-1111-1111-111111111111/telemetry-snapshots?page=-1")
        assert res.status_code == 422
        assert res.headers["content-type"] == "application/problem+json"

        # Size > 100
        res2 = await client.get("/api/v1/vehicles/11111111-1111-1111-1111-111111111111/telemetry-snapshots?size=150")
        assert res2.status_code == 422
        assert res2.headers["content-type"] == "application/problem+json"


@pytest.mark.asyncio
async def test_get_dtc_alerts_success(test_app: FastAPI, mock_mongo_repo):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/api/v1/vehicles/11111111-1111-1111-1111-111111111111/dtc-alerts?page=0&size=20&severity=CRITICAL",
            headers={"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"},
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "alert-1"
        assert data[0]["dtc_code"] == "P0300"
        assert data[0]["severity"] == "CRITICAL"

        mock_mongo_repo.get_paginated_alerts.assert_awaited_with(
            tenant_id="00000000-0000-0000-0000-000000000001",
            vehicle_id="11111111-1111-1111-1111-111111111111",
            page=0,
            size=20,
            severity="CRITICAL",
        )


@pytest.mark.asyncio
async def test_get_dtc_alerts_dual_route(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/iot/vehicles/11111111-1111-1111-1111-111111111111/dtc-alerts")
        assert res.status_code == 200
        assert len(res.json()) == 1


@pytest.mark.asyncio
async def test_multi_tenant_isolation(test_app: FastAPI, mock_timescale_repo, mock_mongo_repo):
    # When requesting vehicle for a different tenant, repository receives the caller's tenant_id
    mock_timescale_repo.get_vehicle_snapshots.return_value = []
    mock_mongo_repo.get_paginated_alerts.return_value = []

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res_ts = await client.get(
            "/api/v1/vehicles/11111111-1111-1111-1111-111111111111/telemetry-snapshots",
            headers={"X-Tenant-ID": "22222222-2222-2222-2222-222222222222"},
        )
        assert res_ts.status_code == 200
        assert res_ts.json() == []

        mock_timescale_repo.get_vehicle_snapshots.assert_awaited_with(
            tenant_id="22222222-2222-2222-2222-222222222222",
            vehicle_id="11111111-1111-1111-1111-111111111111",
            page=0,
            size=20,
        )

        res_dtc = await client.get(
            "/api/v1/vehicles/11111111-1111-1111-1111-111111111111/dtc-alerts",
            headers={"X-Tenant-ID": "22222222-2222-2222-2222-222222222222"},
        )
        assert res_dtc.status_code == 200
        assert res_dtc.json() == []

        mock_mongo_repo.get_paginated_alerts.assert_awaited_with(
            tenant_id="22222222-2222-2222-2222-222222222222",
            vehicle_id="11111111-1111-1111-1111-111111111111",
            page=0,
            size=20,
            severity=None,
        )
