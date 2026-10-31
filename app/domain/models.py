from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class VehicleHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class GPSLocation(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90, 90]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180, 180]")
    altitude: Optional[float] = Field(default=None, description="Altitude in meters")
    heading: Optional[float] = Field(default=None, ge=0.0, le=360.0, description="Direction of travel in degrees [0, 360]")


class OBDData(BaseModel):
    engine_rpm: int = Field(default=0, ge=0, description="Engine speed in RPM")
    speed_kmh: float = Field(default=0.0, ge=0.0, description="Vehicle speed in km/h")
    coolant_temp_c: Optional[int] = Field(default=None, description="Engine coolant temperature in Celsius")
    fuel_level_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Fuel level percentage [0, 100]")
    throttle_position: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Throttle position percentage [0, 100]")
    battery_voltage: Optional[float] = Field(default=None, ge=0.0, le=30.0, description="Battery voltage in Volts")
    dtcs: List[str] = Field(default_factory=list, description="Diagnostic Trouble Codes (e.g. P0300)")

    @field_validator("dtcs", mode="before")
    @classmethod
    def clean_dtcs(cls, v):
        if not v:
            return []
        return [str(code).strip().upper() for code in v if str(code).strip()]


class TelemetryPacket(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = Field(..., min_length=1, description="Tenant UUID")
    vehicle_id: str = Field(..., min_length=1, description="Vehicle UUID")
    device_id: str = Field(..., min_length=1, description="IoT Device ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    location: GPSLocation
    obd: OBDData
    metadata: Optional[Dict[str, str]] = Field(default_factory=dict)


class DiagnosticAlert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    vehicle_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    code: str
    severity: DiagnosticSeverity
    title: str
    description: str
    sensor_values: Dict[str, float] = Field(default_factory=dict)


class VehicleTwinState(BaseModel):
    tenant_id: str
    vehicle_id: str
    last_timestamp: datetime
    last_location: GPSLocation
    last_speed_kmh: float
    last_engine_rpm: int
    last_coolant_temp_c: Optional[int] = None
    last_battery_voltage: Optional[float] = None
    last_fuel_level_percent: Optional[float] = None
    active_dtcs: List[str] = Field(default_factory=list)
    active_alerts: List[DiagnosticAlert] = Field(default_factory=list)
    overall_status: VehicleHealthStatus = VehicleHealthStatus.HEALTHY
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TelemetrySnapshotItem(BaseModel):
    time: datetime
    vehicle_id: str
    device_id: str
    speed_kmh: float
    engine_rpm: int
    coolant_temp_c: Optional[int] = None
    battery_voltage: Optional[float] = None
    fuel_level_percent: Optional[float] = None


class DtcAlertItem(BaseModel):
    id: str
    vehicle_id: str
    dtc_code: str
    description: str
    severity: str
    created_at: datetime
    telemetry_snapshot_id: Optional[str] = None


class DtcAlertTriggeredEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = "DtcAlertTriggered"
    tenant_id: str
    vehicle_id: str
    dtc_code: str
    severity: str
    description: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

