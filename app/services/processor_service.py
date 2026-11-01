import logging
import time
from typing import List, Tuple
from app.api.v1.metrics import (
    DIAGNOSTIC_EVALUATION_LATENCY_SECONDS,
    MONGO_UPDATE_LATENCY_SECONDS,
    TELEMETRY_MESSAGES_PROCESSED_TOTAL,
    TIMESCALE_INSERT_LATENCY_SECONDS,
)
from app.domain.models import DiagnosticAlert, TelemetryPacket, VehicleTwinState
from app.domain.rules import determine_overall_health, evaluate_telemetry_packet
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository

logger = logging.getLogger(__name__)


class ProcessResult(tuple):
    """Result of batch processing returning (timeseries_count, alert_count) with alert details."""

    def __new__(cls, timeseries_count: int, alerts: List[DiagnosticAlert]):
        return super().__new__(cls, (timeseries_count, len(alerts)))

    def __init__(self, timeseries_count: int, alerts: List[DiagnosticAlert]):
        self.timeseries_count = timeseries_count
        self.alert_count = len(alerts)
        self.alerts = alerts


class ProcessorService:
    """Service orchestrating domain evaluation and dual storage persistence."""

    def __init__(self, timescale_repo: TimescaleRepository, mongo_repo: MongoRepository):
        self._timescale_repo = timescale_repo
        self._mongo_repo = mongo_repo

    async def process_batch(self, packets: List[TelemetryPacket]) -> ProcessResult:
        """Process a batch of valid telemetry packets.

        Returns ProcessResult (timeseries_count, emitted_alerts_count).
        """
        if not packets:
            return ProcessResult(0, [])

        # 1. Batch insert into TimescaleDB time-series hypertable
        t0 = time.perf_counter()
        timeseries_count = await self._timescale_repo.insert_batch(packets)
        TIMESCALE_INSERT_LATENCY_SECONDS.observe(time.perf_counter() - t0)

        # 2. Domain evaluation and MongoDB twin/alert updates
        all_alerts: List[DiagnosticAlert] = []
        for packet in packets:
            t_eval = time.perf_counter()
            alerts = evaluate_telemetry_packet(packet)
            DIAGNOSTIC_EVALUATION_LATENCY_SECONDS.observe(time.perf_counter() - t_eval)
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

            t_mongo = time.perf_counter()
            await self._mongo_repo.upsert_vehicle_twin(twin)
            if alerts:
                await self._mongo_repo.save_alerts(alerts)
                all_alerts.extend(alerts)
            MONGO_UPDATE_LATENCY_SECONDS.observe(time.perf_counter() - t_mongo)

        TELEMETRY_MESSAGES_PROCESSED_TOTAL.labels(status="success").inc(len(packets))
        return ProcessResult(timeseries_count, all_alerts)

