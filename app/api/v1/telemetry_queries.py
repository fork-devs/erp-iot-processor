import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_tenant_id, get_mongo_repo, get_timescale_repo
from app.domain.models import DtcAlertItem, TelemetrySnapshotItem, TelemetrySnapshotResource
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vehicle Telemetry & Alerts"])
device_router = APIRouter(tags=["OBD2 Device Telemetry"])



@router.get(
    "/{vehicle_id}/telemetry-snapshots",
    response_model=List[TelemetrySnapshotItem],
    status_code=status.HTTP_200_OK,
    summary="Query historical vehicle telemetry snapshots",
    description="Retrieve paginated time-series telemetry sensor readings for a specific vehicle from TimescaleDB.",
)
async def get_vehicle_telemetry_snapshots(
    vehicle_id: str,
    page: int = Query(default=0, ge=0, description="Page number starting at 0"),
    size: int = Query(default=20, ge=1, le=100, description="Page size up to 100"),
    tenant_id: str = Depends(get_current_tenant_id),
    timescale_repo: TimescaleRepository = Depends(get_timescale_repo),
) -> List[TelemetrySnapshotItem]:
    """Retrieve historical time-series sensor readings for a vehicle with strict tenant isolation."""
    try:
        snapshots = await timescale_repo.get_vehicle_snapshots(
            tenant_id=tenant_id,
            vehicle_id=vehicle_id,
            page=page,
            size=size,
        )
    except Exception as e:
        # Invalid UUID input syntax or unparseable UUID returns empty list (prevent cross-tenant leakage)
        if "uuid" in str(e).lower() or "syntax" in str(e).lower():
            logger.debug(f"Invalid UUID query attempt: {e}")
            return []
        logger.error(f"Error querying telemetry snapshots for vehicle {vehicle_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query telemetry snapshots",
        )

    return [
        TelemetrySnapshotItem(
            time=s["time"],
            vehicle_id=s["vehicle_id"],
            device_id=s["device_id"],
            speed_kmh=s["speed_kmh"],
            engine_rpm=s["engine_rpm"],
            coolant_temp_c=s["coolant_temp_c"],
            battery_voltage=s["battery_voltage"],
            fuel_level_percent=s["fuel_level_percent"],
        )
        for s in snapshots
    ]


@router.get(
    "/{vehicle_id}/dtc-alerts",
    response_model=List[DtcAlertItem],
    status_code=status.HTTP_200_OK,
    summary="Query vehicle DTC and anomaly alerts",
    description="Retrieve paginated diagnostic trouble codes and anomaly alerts for a specific vehicle from MongoDB.",
)
async def get_vehicle_dtc_alerts(
    vehicle_id: str,
    page: int = Query(default=0, ge=0, description="Page number starting at 0"),
    size: int = Query(default=20, ge=1, le=100, description="Page size up to 100"),
    severity: Optional[str] = Query(default=None, description="Optional filter by alert severity (INFO, WARNING, CRITICAL, etc.)"),
    tenant_id: str = Depends(get_current_tenant_id),
    mongo_repo: MongoRepository = Depends(get_mongo_repo),
) -> List[DtcAlertItem]:
    """Retrieve historical diagnostic trouble codes and anomaly alerts with strict tenant isolation."""
    alerts = await mongo_repo.get_paginated_alerts(
        tenant_id=tenant_id,
        vehicle_id=vehicle_id,
        page=page,
        size=size,
        severity=severity,
    )

    return [
        DtcAlertItem(
            id=a.id,
            vehicle_id=a.vehicle_id,
            dtc_code=a.code,
            description=a.description or a.title,
            severity=a.severity.value if hasattr(a.severity, "value") else str(a.severity),
            created_at=a.timestamp,
            telemetry_snapshot_id=None,
        )
        for a in alerts
    ]


@device_router.get(
    "/api/v1/obd2-devices/{deviceId}/telemetry-snapshots/latest",
    response_model=TelemetrySnapshotResource,
    status_code=status.HTTP_200_OK,
    summary="Get latest live telemetry snapshot for device",
    description="Retrieve the most recent live telemetry reading for an OBD2 device.",
)
async def get_latest_device_snapshot(
    deviceId: str,
    tenant_id: str = Depends(get_current_tenant_id),
    timescale_repo: TimescaleRepository = Depends(get_timescale_repo),
) -> TelemetrySnapshotResource:
    """Retrieve the latest live telemetry snapshot for an OBD2 device."""
    try:
        snapshot = await timescale_repo.get_latest_device_snapshot(
            tenant_id=tenant_id,
            device_id=deviceId,
        )
    except Exception as e:
        logger.error(f"Error querying latest snapshot for device {deviceId}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query latest telemetry snapshot",
        )

    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry snapshot found for device {deviceId}",
        )

    return TelemetrySnapshotResource(
        id=f"snap-{snapshot['device_id']}-{int(snapshot['time'].timestamp())}",
        deviceId=snapshot["device_id"],
        vehicleId=snapshot["vehicle_id"],
        rpm=snapshot["engine_rpm"],
        temperature=snapshot["coolant_temp_c"],
        speedKmh=snapshot["speed_kmh"],
        batteryVoltage=snapshot["battery_voltage"],
        fuelLevelPercent=snapshot["fuel_level_percent"],
        createdAt=snapshot["time"],
    )


@device_router.get(
    "/api/v1/obd2-devices/{deviceId}/telemetry-snapshots",
    response_model=List[TelemetrySnapshotResource],
    status_code=status.HTTP_200_OK,
    summary="Get telemetry snapshots history for device",
    description="Retrieve paginated historical telemetry snapshots for an OBD2 device.",
)
async def get_device_telemetry_snapshots(
    deviceId: str,
    page: int = Query(default=0, ge=0, description="Page number starting at 0"),
    size: int = Query(default=20, ge=1, le=100, description="Page size up to 100"),
    tenant_id: str = Depends(get_current_tenant_id),
    timescale_repo: TimescaleRepository = Depends(get_timescale_repo),
) -> List[TelemetrySnapshotResource]:
    """Retrieve historical telemetry snapshots for an OBD2 device."""
    try:
        snapshots = await timescale_repo.get_device_snapshots(
            tenant_id=tenant_id,
            device_id=deviceId,
            page=page,
            size=size,
        )
    except Exception as e:
        logger.error(f"Error querying snapshots for device {deviceId}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query device telemetry snapshots",
        )

    return [
        TelemetrySnapshotResource(
            id=f"snap-{s['device_id']}-{int(s['time'].timestamp())}",
            deviceId=s["device_id"],
            vehicleId=s["vehicle_id"],
            rpm=s["engine_rpm"],
            temperature=s["coolant_temp_c"],
            speedKmh=s["speed_kmh"],
            batteryVoltage=s["battery_voltage"],
            fuelLevelPercent=s["fuel_level_percent"],
            createdAt=s["time"],
        )
        for s in snapshots
    ]


@device_router.get(
    "/api/v1/obd2-device-registrations/{id}/telemetry-snapshots",
    response_model=List[TelemetrySnapshotResource],
    status_code=status.HTTP_200_OK,
    summary="Get telemetry snapshots for a device registration",
    description="Retrieve paginated telemetry readings captured under a specific vehicle device registration.",
)
async def get_registration_telemetry_snapshots(
    id: str,
    page: int = Query(default=0, ge=0, description="Page number starting at 0"),
    size: int = Query(default=20, ge=1, le=100, description="Page size up to 100"),
    tenant_id: str = Depends(get_current_tenant_id),
    timescale_repo: TimescaleRepository = Depends(get_timescale_repo),
) -> List[TelemetrySnapshotResource]:
    """Retrieve telemetry snapshots associated with a device registration."""
    try:
        snapshots = await timescale_repo.get_registration_snapshots(
            tenant_id=tenant_id,
            registration_id=id,
            page=page,
            size=size,
        )
    except Exception as e:
        logger.error(f"Error querying registration snapshots for {id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query registration telemetry snapshots",
        )

    return [
        TelemetrySnapshotResource(
            id=f"snap-{s['device_id']}-{int(s['time'].timestamp())}",
            obd2DeviceRegistrationId=id,
            deviceId=s["device_id"],
            vehicleId=s["vehicle_id"],
            rpm=s["engine_rpm"],
            temperature=s["coolant_temp_c"],
            speedKmh=s["speed_kmh"],
            batteryVoltage=s["battery_voltage"],
            fuelLevelPercent=s["fuel_level_percent"],
            createdAt=s["time"],
        )
        for s in snapshots
    ]


@device_router.get(
    "/api/v1/obd2-device-registrations/{id}/dtc-alerts",
    response_model=List[DtcAlertItem],
    status_code=status.HTTP_200_OK,
    summary="Get DTC alerts for a device registration",
    description="Retrieve paginated diagnostic trouble codes and anomaly alerts for a specific device registration.",
)
async def get_registration_dtc_alerts(
    id: str,
    page: int = Query(default=0, ge=0, description="Page number starting at 0"),
    size: int = Query(default=20, ge=1, le=100, description="Page size up to 100"),
    tenant_id: str = Depends(get_current_tenant_id),
    mongo_repo: MongoRepository = Depends(get_mongo_repo),
) -> List[DtcAlertItem]:
    """Retrieve diagnostic alerts detected during a specific device registration."""
    try:
        alerts = await mongo_repo.get_registration_alerts(
            tenant_id=tenant_id,
            registration_id=id,
            page=page,
            size=size,
        )
    except Exception as e:
        logger.error(f"Error querying registration DTC alerts for {id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to query registration DTC alerts",
        )

    return [
        DtcAlertItem(
            id=a.id,
            vehicle_id=a.vehicle_id,
            dtc_code=a.code,
            description=a.description or a.title,
            severity=a.severity.value if hasattr(a.severity, "value") else str(a.severity),
            created_at=a.timestamp,
            telemetry_snapshot_id=None,
        )
        for a in alerts
    ]

