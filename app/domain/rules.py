from typing import List
import uuid
from app.domain.dtc_catalog import lookup_dtc
from app.domain.models import (
    DiagnosticAlert,
    DiagnosticSeverity,
    TelemetryPacket,
    VehicleHealthStatus,
)


# Physical threshold constants
COOLANT_TEMP_CRITICAL_C = 115
COOLANT_TEMP_WARNING_C = 105
ENGINE_RPM_OVERREV_LIMIT = 6000
BATTERY_VOLTAGE_LOW_LIMIT = 11.8
BATTERY_VOLTAGE_CRITICAL_LIMIT = 10.5
FUEL_LEVEL_LOW_PERCENT = 5.0


def evaluate_telemetry_packet(packet: TelemetryPacket) -> List[DiagnosticAlert]:
    """Evaluate physical sensor boundaries and DTCs, returning emitted diagnostic alerts."""
    alerts: List[DiagnosticAlert] = []
    obd = packet.obd

    # 1. Evaluate OBD-II Diagnostic Trouble Codes
    for code in obd.dtcs:
        entry = lookup_dtc(code)
        alerts.append(
            DiagnosticAlert(
                id=str(uuid.uuid4()),
                tenant_id=packet.tenant_id,
                vehicle_id=packet.vehicle_id,
                timestamp=packet.timestamp,
                code=entry.code,
                severity=entry.severity,
                title=entry.title,
                description=entry.description,
                sensor_values={"speed_kmh": obd.speed_kmh, "engine_rpm": float(obd.engine_rpm)},
            )
        )

    # 2. Coolant temperature threshold
    if obd.coolant_temp_c is not None:
        if obd.coolant_temp_c >= COOLANT_TEMP_CRITICAL_C:
            alerts.append(
                DiagnosticAlert(
                    id=str(uuid.uuid4()),
                    tenant_id=packet.tenant_id,
                    vehicle_id=packet.vehicle_id,
                    timestamp=packet.timestamp,
                    code="ANOMALY_OVERHEAT_CRITICAL",
                    severity=DiagnosticSeverity.CRITICAL,
                    title="Critical Engine Overheating",
                    description=f"Coolant temperature reached {obd.coolant_temp_c}°C exceeding critical limit ({COOLANT_TEMP_CRITICAL_C}°C).",
                    sensor_values={"coolant_temp_c": float(obd.coolant_temp_c)},
                )
            )
        elif obd.coolant_temp_c >= COOLANT_TEMP_WARNING_C:
            alerts.append(
                DiagnosticAlert(
                    id=str(uuid.uuid4()),
                    tenant_id=packet.tenant_id,
                    vehicle_id=packet.vehicle_id,
                    timestamp=packet.timestamp,
                    code="ANOMALY_OVERHEAT_WARNING",
                    severity=DiagnosticSeverity.WARNING,
                    title="Engine Temperature Warning",
                    description=f"Coolant temperature is elevated at {obd.coolant_temp_c}°C (threshold: {COOLANT_TEMP_WARNING_C}°C).",
                    sensor_values={"coolant_temp_c": float(obd.coolant_temp_c)},
                )
            )

    # 3. Engine Over-rev threshold
    if obd.engine_rpm >= ENGINE_RPM_OVERREV_LIMIT:
        alerts.append(
            DiagnosticAlert(
                id=str(uuid.uuid4()),
                tenant_id=packet.tenant_id,
                vehicle_id=packet.vehicle_id,
                timestamp=packet.timestamp,
                code="ANOMALY_OVERREV",
                severity=DiagnosticSeverity.WARNING,
                title="Engine Over-Revving Detected",
                description=f"Engine RPM reached {obd.engine_rpm} exceeding safety limit ({ENGINE_RPM_OVERREV_LIMIT} RPM).",
                sensor_values={"engine_rpm": float(obd.engine_rpm), "speed_kmh": obd.speed_kmh},
            )
        )

    # 4. Battery / Alternator voltage threshold
    if obd.battery_voltage is not None:
        if obd.battery_voltage < BATTERY_VOLTAGE_CRITICAL_LIMIT:
            alerts.append(
                DiagnosticAlert(
                    id=str(uuid.uuid4()),
                    tenant_id=packet.tenant_id,
                    vehicle_id=packet.vehicle_id,
                    timestamp=packet.timestamp,
                    code="ANOMALY_BATTERY_CRITICAL",
                    severity=DiagnosticSeverity.CRITICAL,
                    title="Critical Battery Voltage Drop",
                    description=f"Battery voltage dropped to {obd.battery_voltage:.1f}V (critical threshold: {BATTERY_VOLTAGE_CRITICAL_LIMIT}V).",
                    sensor_values={"battery_voltage": obd.battery_voltage},
                )
            )
        elif obd.battery_voltage < BATTERY_VOLTAGE_LOW_LIMIT and obd.speed_kmh > 0:
            alerts.append(
                DiagnosticAlert(
                    id=str(uuid.uuid4()),
                    tenant_id=packet.tenant_id,
                    vehicle_id=packet.vehicle_id,
                    timestamp=packet.timestamp,
                    code="ANOMALY_ALTERNATOR_UNDERVOLTAGE",
                    severity=DiagnosticSeverity.WARNING,
                    title="Alternator Undervoltage in Motion",
                    description=f"Charging voltage is low ({obd.battery_voltage:.1f}V) while vehicle is moving at {obd.speed_kmh:.1f} km/h.",
                    sensor_values={"battery_voltage": obd.battery_voltage, "speed_kmh": obd.speed_kmh},
                )
            )

    # 5. Low fuel level warning
    if obd.fuel_level_percent is not None and obd.fuel_level_percent <= FUEL_LEVEL_LOW_PERCENT:
        alerts.append(
            DiagnosticAlert(
                id=str(uuid.uuid4()),
                tenant_id=packet.tenant_id,
                vehicle_id=packet.vehicle_id,
                timestamp=packet.timestamp,
                code="ANOMALY_LOW_FUEL",
                severity=DiagnosticSeverity.INFO,
                title="Low Fuel Level Warning",
                description=f"Fuel level is at {obd.fuel_level_percent:.1f}% (reserve threshold: {FUEL_LEVEL_LOW_PERCENT}%).",
                sensor_values={"fuel_level_percent": obd.fuel_level_percent},
            )
        )

    return alerts


def determine_overall_health(alerts: List[DiagnosticAlert]) -> VehicleHealthStatus:
    """Calculate overall vehicle health based on active diagnostic alerts."""
    if any(a.severity == DiagnosticSeverity.CRITICAL for a in alerts):
        return VehicleHealthStatus.CRITICAL
    if any(a.severity == DiagnosticSeverity.WARNING for a in alerts):
        return VehicleHealthStatus.WARNING
    return VehicleHealthStatus.HEALTHY
