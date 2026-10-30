from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_current_tenant_id, get_mongo_repo
from app.repositories.mongo_repo import MongoRepository

router = APIRouter(prefix="/api/v1/iot", tags=["Vehicle Diagnostics"])


@router.get("/diagnostics/{vehicle_id}", status_code=status.HTTP_200_OK)
async def get_vehicle_diagnostics(
    vehicle_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    mongo_repo: MongoRepository = Depends(get_mongo_repo),
) -> Dict[str, Any]:
    """Retrieve the current consolidated diagnostic twin status and recent trouble alerts."""
    twin = await mongo_repo.get_vehicle_twin(tenant_id=tenant_id, vehicle_id=vehicle_id)
    if not twin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic twin for vehicle '{vehicle_id}' not found",
        )

    recent_alerts = await mongo_repo.get_recent_alerts(tenant_id=tenant_id, vehicle_id=vehicle_id, limit=20)

    return {
        "tenant_id": twin.tenant_id,
        "vehicle_id": twin.vehicle_id,
        "overall_status": twin.overall_status.value,
        "last_timestamp": twin.last_timestamp.isoformat(),
        "last_location": twin.last_location.model_dump(),
        "last_speed_kmh": twin.last_speed_kmh,
        "last_engine_rpm": twin.last_engine_rpm,
        "last_coolant_temp_c": twin.last_coolant_temp_c,
        "last_battery_voltage": twin.last_battery_voltage,
        "last_fuel_level_percent": twin.last_fuel_level_percent,
        "active_dtcs": twin.active_dtcs,
        "active_alerts": [a.model_dump(mode="json") for a in twin.active_alerts],
        "recent_alerts": [a.model_dump(mode="json") for a in recent_alerts],
        "updated_at": twin.updated_at.isoformat(),
    }
