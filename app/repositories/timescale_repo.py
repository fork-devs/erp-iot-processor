import logging
from typing import List, Optional
import asyncpg
from app.domain.models import TelemetryPacket

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS vehicle_telemetry_history (
    time TIMESTAMPTZ NOT NULL,
    tenant_id UUID NOT NULL,
    vehicle_id UUID NOT NULL,
    device_id VARCHAR(64) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    altitude DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    speed_kmh DOUBLE PRECISION NOT NULL,
    engine_rpm INTEGER NOT NULL,
    coolant_temp_c INTEGER,
    battery_voltage DOUBLE PRECISION,
    fuel_level_percent DOUBLE PRECISION,
    PRIMARY KEY (time, tenant_id, vehicle_id)
);
CREATE INDEX IF NOT EXISTS idx_telemetry_tenant_vehicle ON vehicle_telemetry_history (tenant_id, vehicle_id, time DESC);
"""

INSERT_BATCH_SQL = """
INSERT INTO vehicle_telemetry_history (
    time, tenant_id, vehicle_id, device_id, latitude, longitude, altitude, heading,
    speed_kmh, engine_rpm, coolant_temp_c, battery_voltage, fuel_level_percent
) VALUES (
    $1, $2::uuid, $3::uuid, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13
)
ON CONFLICT (time, tenant_id, vehicle_id) DO NOTHING;
"""


class TimescaleRepository:
    """Repository managing time-series telemetry persistence in TimescaleDB / PostgreSQL."""

    def __init__(self, pool: Optional[asyncpg.Pool] = None):
        self._pool = pool

    def set_pool(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def init_schema(self) -> None:
        """Create hypertable schema if it does not exist."""
        if not self._pool:
            raise RuntimeError("TimescaleRepository pool is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
            # Try converting to hypertable if TimescaleDB extension exists
            try:
                await conn.execute("SELECT create_hypertable('vehicle_telemetry_history', 'time', if_not_exists => TRUE);")
            except Exception as e:
                logger.debug(f"Timescale hypertable creation skipped (standard Postgres fallback): {e}")

    async def insert_batch(self, packets: List[TelemetryPacket]) -> int:
        """Persist a batch of telemetry packets asynchronously."""
        if not packets:
            return 0
        if not self._pool:
            raise RuntimeError("TimescaleRepository pool is not initialized")

        records = [
            (
                p.timestamp,
                p.tenant_id,
                p.vehicle_id,
                p.device_id,
                p.location.latitude,
                p.location.longitude,
                p.location.altitude,
                p.location.heading,
                p.obd.speed_kmh,
                p.obd.engine_rpm,
                p.obd.coolant_temp_c,
                p.obd.battery_voltage,
                p.obd.fuel_level_percent,
            )
            for p in packets
        ]

        async with self._pool.acquire() as conn:
            await conn.executemany(INSERT_BATCH_SQL, records)
        return len(records)

    async def get_vehicle_snapshots(
        self, tenant_id: str, vehicle_id: str, page: int = 0, size: int = 20
    ) -> List[dict]:
        """Fetch historical time-series snapshots for a vehicle with pagination."""
        if not self._pool:
            raise RuntimeError("TimescaleRepository pool is not initialized")

        offset = max(0, page) * size
        query = """
        SELECT
            time,
            tenant_id::text,
            vehicle_id::text,
            device_id,
            speed_kmh,
            engine_rpm,
            coolant_temp_c,
            battery_voltage,
            fuel_level_percent
        FROM vehicle_telemetry_history
        WHERE tenant_id = $1::uuid AND vehicle_id = $2::uuid
        ORDER BY time DESC
        LIMIT $3 OFFSET $4;
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, vehicle_id, size, offset)
            return [
                {
                    "time": r["time"],
                    "tenant_id": r["tenant_id"],
                    "vehicle_id": r["vehicle_id"],
                    "device_id": r["device_id"],
                    "speed_kmh": r["speed_kmh"],
                    "engine_rpm": r["engine_rpm"],
                    "coolant_temp_c": r["coolant_temp_c"],
                    "battery_voltage": r["battery_voltage"],
                    "fuel_level_percent": r["fuel_level_percent"],
                }
                for r in rows
            ]

    async def health_check(self) -> bool:
        """Verify database connectivity."""
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                res = await conn.fetchval("SELECT 1")
                return res == 1
        except Exception as e:
            logger.warning(f"TimescaleDB health check failed: {e}")
            return False
