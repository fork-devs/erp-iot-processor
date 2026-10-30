import logging
from typing import List, Tuple
from app.domain.models import DiagnosticAlert, TelemetryPacket, VehicleTwinState
from app.domain.rules import determine_overall_health, evaluate_telemetry_packet
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository

logger = logging.getLogger(__name__)


class ProcessorService:
    """Service orchestrating domain evaluation and dual storage persistence."""

    def __init__(self, timescale_repo: TimescaleRepository, mongo_repo: MongoRepository):
        self._timescale_repo = timescale_repo
        self._mongo_repo = mongo_repo

    async def process_batch(self, packets: List[TelemetryPacket]) -> Tuple[int, int]:
        """Process a batch of valid telemetry packets.

        Returns (persisted_timeseries_count, emitted_alerts_count).
        """
        if not packets:
            return 0, 0

        # 1. Batch insert into TimescaleDB time-series hypertable
        timeseries_count = await self._timescale_repo.insert_batch(packets)

        # 2. Domain evaluation and MongoDB twin/alert updates
        total_alerts = 0
        for packet in packets:
            alerts = evaluate_telemetry_packet(packet)
            health_status = determine_overall_health(alerts)

            twin = VehicleTwinState(
                tenant_id=packet.tenant_id,
                vehicle_id=packet.vehicle_id,
                last_timestamp=packet.timestamp,
                last_location=packet.location,
                last_speed_kmh=packet.obd.speed_kmh,
                last_engine_rpm=packet.obd.engine_rpm,
                last_coolant_temp_c=packet.obd.coolant_temp_c,
                last_battery_voltage=packet.obd.battery_voltage,
                last_fuel_level_percent=packet.obd.fuel_level_percent,
                active_dtcs=packet.obd.dtcs,
                active_alerts=alerts,
                overall_status=health_status,
            )

            await self._mongo_repo.upsert_vehicle_twin(twin)
            if alerts:
                await self._mongo_repo.save_alerts(alerts)
                total_alerts += len(alerts)

        return timeseries_count, total_alerts
