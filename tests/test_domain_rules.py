from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.domain.dtc_catalog import lookup_dtc
from app.domain.models import (
    DiagnosticSeverity,
    GPSLocation,
    OBDData,
    TelemetryPacket,
    VehicleHealthStatus,
)
from app.domain.rules import determine_overall_health, evaluate_telemetry_packet


def test_gps_location_validation():
    loc = GPSLocation(latitude=-12.0464, longitude=-77.0428, altitude=150.0, heading=90.0)
    assert loc.latitude == -12.0464
    assert loc.longitude == -77.0428

    with pytest.raises(ValidationError):
        GPSLocation(latitude=95.0, longitude=0.0)

    with pytest.raises(ValidationError):
        GPSLocation(latitude=0.0, longitude=-190.0)


def test_obd_data_validation():
    obd = OBDData(engine_rpm=2500, speed_kmh=80.0, coolant_temp_c=90, dtcs=["p0300", " p0171 "])
    assert obd.engine_rpm == 2500
    assert obd.dtcs == ["P0300", "P0171"]

    with pytest.raises(ValidationError):
        OBDData(engine_rpm=-100)

    with pytest.raises(ValidationError):
        OBDData(speed_kmh=-10.0)


def test_dtc_catalog_lookup():
    # Known critical
    entry_p0300 = lookup_dtc("P0300")
    assert entry_p0300.severity == DiagnosticSeverity.CRITICAL
    assert entry_p0300.system == "Powertrain"

    # Known warning
    entry_p0171 = lookup_dtc("P0171")
    assert entry_p0171.severity == DiagnosticSeverity.WARNING

    # Known network critical
    entry_u0100 = lookup_dtc("U0100")
    assert entry_u0100.severity == DiagnosticSeverity.CRITICAL

    # Unknown code falls back to prefix inference
    entry_unknown_p = lookup_dtc("P9999")
    assert entry_unknown_p.severity == DiagnosticSeverity.WARNING
    assert entry_unknown_p.system == "Powertrain"

    entry_unknown_b = lookup_dtc("B9999")
    assert entry_unknown_b.severity == DiagnosticSeverity.INFO


def test_evaluate_clean_telemetry():
    packet = TelemetryPacket(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        device_id="OBD-DONGLE-01",
        timestamp=datetime.now(timezone.utc),
        location=GPSLocation(latitude=-12.0, longitude=-77.0),
        obd=OBDData(
            engine_rpm=2000,
            speed_kmh=60.0,
            coolant_temp_c=90,
            battery_voltage=13.8,
            fuel_level_percent=60.0,
            dtcs=[],
        ),
    )

    alerts = evaluate_telemetry_packet(packet)
    assert len(alerts) == 0
    assert determine_overall_health(alerts) == VehicleHealthStatus.HEALTHY


def test_evaluate_critical_overheating():
    packet = TelemetryPacket(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        device_id="OBD-DONGLE-01",
        location=GPSLocation(latitude=-12.0, longitude=-77.0),
        obd=OBDData(
            coolant_temp_c=120,
            engine_rpm=2500,
            speed_kmh=40.0,
        ),
    )

    alerts = evaluate_telemetry_packet(packet)
    assert len(alerts) == 1
    assert alerts[0].code == "ANOMALY_OVERHEAT_CRITICAL"
    assert alerts[0].severity == DiagnosticSeverity.CRITICAL
    assert determine_overall_health(alerts) == VehicleHealthStatus.CRITICAL


def test_evaluate_overrev_and_low_battery():
    packet = TelemetryPacket(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        device_id="OBD-DONGLE-01",
        location=GPSLocation(latitude=-12.0, longitude=-77.0),
        obd=OBDData(
            engine_rpm=6500,
            speed_kmh=75.0,
            battery_voltage=11.2,
            dtcs=["P0300"],
        ),
    )

    alerts = evaluate_telemetry_packet(packet)
    codes = {a.code for a in alerts}
    assert "ANOMALY_OVERREV" in codes
    assert "ANOMALY_ALTERNATOR_UNDERVOLTAGE" in codes
    assert "P0300" in codes

    # Due to P0300 (CRITICAL misfire), status must be CRITICAL
    assert determine_overall_health(alerts) == VehicleHealthStatus.CRITICAL
