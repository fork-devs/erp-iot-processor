from datetime import datetime, timezone
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from httpx import AsyncClient, HTTPError
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime

from app.api.deps import AuthenticatedUser, get_authenticated_user, get_mongo_repo
from app.core.config import get_settings
from app.domain.models import DiagnosticSeverity
from app.domain.preventive_alerts import AlertStatus, PreventiveAlert, ScheduleService, StatusChange, UpdateAlertStatus
from app.repositories.mongo_repo import MongoRepository
from app.repositories.preventive_alerts import PreventiveAlertRepository

router = APIRouter(prefix="/api/v1/iot/alerts", tags=["Preventive alerts"])
WORKSHOP_ROLES = {"SUPERADMIN", "WORKSHOP_ADMIN", "ADMIN_TALLER", "SERVICE_ADVISOR", "ASESOR"}


def get_alert_repository(mongo: MongoRepository = Depends(get_mongo_repo)) -> PreventiveAlertRepository:
    return mongo.preventive_alerts()


def get_workshop_user(user: AuthenticatedUser = Depends(get_authenticated_user)) -> AuthenticatedUser:
    if WORKSHOP_ROLES.isdisjoint(user.roles):
        raise HTTPException(403, "Workshop manager or service advisor role required")
    return user


WorkshopUser = Annotated[AuthenticatedUser, Depends(get_workshop_user)]
AlertRepository = Annotated[PreventiveAlertRepository, Depends(get_alert_repository)]


@router.get("", response_model=list[PreventiveAlert])
async def list_alerts(
    user: WorkshopUser,
    repository: AlertRepository,
    vehicle_id: str | None = None,
    customer_id: UUID | None = None,
    severity: DiagnosticSeverity | None = None,
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
    page: Annotated[int, Query(ge=0)] = 0,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    if since is not None and until is not None and since > until:
        raise HTTPException(422, "The date range is invalid")
    vehicle_filter: str | list[str] | None = vehicle_id
    if customer_id is not None:
        base_url = get_settings().FLEET_SERVICE_URL.rstrip("/")
        try:
            async with AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
                response = await client.get(
                    f"{base_url}/api/v1/fleet/vehicles/customer/{customer_id}",
                    headers={"Authorization": f"Bearer {user.token}", "X-Tenant-ID": user.tenant_id},
                )
                response.raise_for_status()
                customer_vehicles = [str(UUID(row["id"])) for row in response.json()]
        except (HTTPError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(503, "No se pudieron consultar los vehículos del cliente.") from None
        if vehicle_id and vehicle_id not in customer_vehicles:
            return []
        vehicle_filter = vehicle_id or customer_vehicles
    return await repository.search(user.tenant_id, vehicle_filter, severity, alert_status, since, until, page, size)


@router.patch("/{alert_id}/status", response_model=PreventiveAlert)
async def update_alert_status(alert_id: str, update: UpdateAlertStatus, user: WorkshopUser, repository: AlertRepository):
    alert = await repository.get(user.tenant_id, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    if alert.status == update.status:
        return alert
    change = StatusChange(
        status=update.status, changed_at=datetime.now(timezone.utc), changed_by=user.subject, reason=update.reason,
    )
    updated = await repository.change_status(user.tenant_id, alert, change)
    if updated is None:
        raise HTTPException(409, "The alert changed or has an appointment being scheduled")
    return updated


@router.post("/{alert_id}/schedule-service", response_model=PreventiveAlert, status_code=status.HTTP_201_CREATED)
async def schedule_service(alert_id: str, request: ScheduleService, user: WorkshopUser, repository: AlertRepository):
    alert = await repository.get(user.tenant_id, alert_id)
    if alert is None:
        raise HTTPException(404, "Alert not found")
    payload = request.model_dump(mode="json", exclude_none=True)
    if alert.appointment_id is not None:
        if alert.appointment_request is not None and alert.appointment_request != payload:
            raise HTTPException(409, "The alert already has a different appointment")
        return alert
    if alert.status in {AlertStatus.ATTENDED, AlertStatus.DISMISSED}:
        raise HTTPException(409, "Only pending alerts or alerts under review can be scheduled")

    lease = await repository.claim_scheduling(user.tenant_id, alert_id, payload)
    if lease is None:
        raise HTTPException(409, "A scheduling request is in progress. Retry with the initial dates and branch.")
    alert_key = uuid5(NAMESPACE_URL, f"driveos:{user.tenant_id}:{alert_id}")
    base_url = get_settings().FLEET_SERVICE_URL.rstrip("/")
    try:
        async with AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            response = await client.put(
                f"{base_url}/api/v1/fleet/appointments/from-alerts/{alert_key}",
                headers={"Authorization": f"Bearer {user.token}", "X-Tenant-ID": user.tenant_id},
                json={
                    "branchId": str(request.branch_id),
                    "vehicleId": alert.vehicle_id,
                    "scheduledStart": request.scheduled_start.isoformat(),
                    "scheduledEnd": request.scheduled_end.isoformat(),
                    "notes": f"{alert.code}: {alert.description}"[:500],
                    "bayNumber": request.bay_number,
                    "technicianId": str(request.technician_id) if request.technician_id is not None else None,
                },
            )
        if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
            await repository.release_scheduling(user.tenant_id, alert_id, lease, retry_only=False)
            raise HTTPException(
                response.status_code,
                "No se pudo reservar el horario. Comprueba la disponibilidad del vehículo, la bahía y el técnico.",
            )
        response.raise_for_status()
        appointment_id = UUID(response.json()["id"])
    except (HTTPError, ValueError, TypeError, KeyError):
        await repository.release_scheduling(user.tenant_id, alert_id, lease, retry_only=True)
        raise HTTPException(503, "Appointment could not be confirmed. Retry with the same dates and branch.") from None

    updated = await repository.finish_scheduling(user.tenant_id, alert_id, lease, appointment_id, user.subject, payload)
    if updated is None:
        current = await repository.get(user.tenant_id, alert_id)
        if current is not None and current.appointment_id == appointment_id:
            return current
        raise HTTPException(503, "The appointment exists. Retry the same request to link it to the alert.")
    return updated
