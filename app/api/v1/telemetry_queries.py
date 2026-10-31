import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_current_tenant_id, get_mongo_repo, get_timescale_repo
from app.domain.models import DtcAlertItem, TelemetrySnapshotItem
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Vehicle Telemetry & Alerts"])


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
