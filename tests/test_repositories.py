from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.domain.models import (
    DiagnosticAlert,
    DiagnosticSeverity,
    GPSLocation,
    OBDData,
    TelemetryPacket,
    VehicleHealthStatus,
    VehicleTwinState,
)
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository


@pytest.fixture
def sample_packet() -> TelemetryPacket:
    return TelemetryPacket(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        device_id="DONGLE-01",
        timestamp=datetime.now(timezone.utc),
        location=GPSLocation(latitude=-12.0464, longitude=-77.0428, altitude=150.0, heading=45.0),
        obd=OBDData(engine_rpm=2200, speed_kmh=65.0, coolant_temp_c=90, battery_voltage=13.6, fuel_level_percent=55.0),
    )


@pytest.fixture
def sample_twin(sample_packet: TelemetryPacket) -> VehicleTwinState:
    return VehicleTwinState(
        tenant_id=sample_packet.tenant_id,
        vehicle_id=sample_packet.vehicle_id,
        last_timestamp=sample_packet.timestamp,
        last_location=sample_packet.location,
        last_speed_kmh=sample_packet.obd.speed_kmh,
        last_engine_rpm=sample_packet.obd.engine_rpm,
        last_coolant_temp_c=sample_packet.obd.coolant_temp_c,
        last_battery_voltage=sample_packet.obd.battery_voltage,
        last_fuel_level_percent=sample_packet.obd.fuel_level_percent,
        active_dtcs=[],
        active_alerts=[],
        overall_status=VehicleHealthStatus.HEALTHY,
    )


@pytest.mark.asyncio
async def test_timescale_repo_insert_batch(sample_packet: TelemetryPacket):
    mock_conn = AsyncMock()
    mock_conn.executemany = AsyncMock()

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAcquireContext()

    repo = TimescaleRepository(pool=mock_pool)
    count = await repo.insert_batch([sample_packet])

    assert count == 1
    mock_conn.executemany.assert_awaited_once()


@pytest.mark.asyncio
async def test_timescale_repo_health_check():
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAcquireContext()

    repo = TimescaleRepository(pool=mock_pool)
    assert await repo.health_check() is True

    # When exception raised
    mock_conn.fetchval = AsyncMock(side_effect=Exception("DB down"))
    assert await repo.health_check() is False


@pytest.mark.asyncio
async def test_mongo_repo_upsert_and_get(sample_twin: VehicleTwinState):
    mock_db = MagicMock()
    mock_db.vehicle_twins.update_one = AsyncMock()
    mock_db.vehicle_twins.find_one = AsyncMock(return_value=sample_twin.model_dump(mode="json"))

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    repo = MongoRepository(client=mock_client)
    await repo.upsert_vehicle_twin(sample_twin)
    mock_db.vehicle_twins.update_one.assert_awaited_once()

    retrieved = await repo.get_vehicle_twin(sample_twin.tenant_id, sample_twin.vehicle_id)
    assert retrieved is not None
    assert retrieved.vehicle_id == sample_twin.vehicle_id
    assert retrieved.overall_status == VehicleHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_mongo_repo_save_alerts():
    alert = DiagnosticAlert(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        code="ANOMALY_OVERREV",
        severity=DiagnosticSeverity.WARNING,
        title="Overrev",
        description="Overrev test",
    )

    mock_insert_res = MagicMock()
    mock_insert_res.inserted_ids = ["id-1"]

    mock_db = MagicMock()
    mock_db.diagnostic_alerts.insert_many = AsyncMock(return_value=mock_insert_res)

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    repo = MongoRepository(client=mock_client)
    count = await repo.save_alerts([alert])
    assert count == 1
    mock_db.diagnostic_alerts.insert_many.assert_awaited_once()


@pytest.mark.asyncio
async def test_timescale_repo_get_vehicle_snapshots():
    mock_conn = AsyncMock()
    now = datetime.now(timezone.utc)
    mock_conn.fetch = AsyncMock(
        return_value=[
            {
                "time": now,
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "vehicle_id": "11111111-1111-1111-1111-111111111111",
                "device_id": "DONGLE-01",
                "speed_kmh": 65.0,
                "engine_rpm": 2200,
                "coolant_temp_c": 90,
                "battery_voltage": 13.6,
                "fuel_level_percent": 55.0,
            }
        ]
    )

    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockAcquireContext()

    repo = TimescaleRepository(pool=mock_pool)
    snapshots = await repo.get_vehicle_snapshots(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        page=0,
        size=20,
    )
    assert len(snapshots) == 1
    assert snapshots[0]["speed_kmh"] == 65.0
    mock_conn.fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_mongo_repo_get_paginated_alerts():
    alert_doc = {
        "_id": "dummy-id",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "vehicle_id": "11111111-1111-1111-1111-111111111111",
        "code": "P0117",
        "severity": "CRITICAL",
        "title": "Engine Coolant Temperature Circuit Low",
        "description": "Short to ground",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resolved": False,
        "resolved_at": None,
        "metadata": {},
    }

    class MockAsyncCursor:
        def __init__(self, items):
            self.items = items

        def sort(self, *args, **kwargs):
            return self

        def skip(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def __aiter__(self):
            self._iter = iter(self.items)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

    mock_db = MagicMock()
    mock_db.diagnostic_alerts.find.return_value = MockAsyncCursor([alert_doc])

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    repo = MongoRepository(client=mock_client)
    alerts = await repo.get_paginated_alerts(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        page=0,
        size=20,
        severity="CRITICAL",
    )
    assert len(alerts) == 1
    assert alerts[0].code == "P0117"
    assert alerts[0].severity == DiagnosticSeverity.CRITICAL
    mock_db.diagnostic_alerts.find.assert_called_once()

