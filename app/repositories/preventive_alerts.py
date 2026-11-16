from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.domain.models import DiagnosticSeverity
from app.domain.preventive_alerts import AlertStatus, PreventiveAlert, StatusChange


class PreventiveAlertRepository:
    """Manages the workflow on the existing diagnostic alert collection."""

    def __init__(self, collection: AsyncIOMotorCollection):
        self._alerts = collection

    async def search(
        self, tenant_id: str, vehicle_id: str | list[str] | None, severity: DiagnosticSeverity | None,
        status: AlertStatus | None, since: datetime | None, until: datetime | None, page: int, size: int,
    ) -> list[PreventiveAlert]:
        query = {"tenant_id": tenant_id}
        for field, value in (("vehicle_id", vehicle_id), ("severity", severity), ("status", status)):
            if value is not None:
                query[field] = value
        if isinstance(vehicle_id, list):
            query["vehicle_id"] = {"$in": vehicle_id}
        if status == AlertStatus.PENDING:
            query["status"] = {"$in": [AlertStatus.PENDING, None]}

        filters = []
        for operator, boundary in (("$gte", since), ("$lte", until)):
            if boundary is not None:
                filters.append({operator: [{"$toDate": "$timestamp"}, boundary]})
        if filters:
            query["$expr"] = {"$and": filters}

        cursor = self._alerts.find(query).sort([("timestamp", -1), ("id", 1)]).skip(page * size).limit(size)
        return [PreventiveAlert.model_validate(document) async for document in cursor]

    async def get(self, tenant_id: str, alert_id: str) -> PreventiveAlert | None:
        document = await self._alerts.find_one({"tenant_id": tenant_id, "id": alert_id})
        return PreventiveAlert.model_validate(document) if document else None

    async def change_status(self, tenant_id: str, alert: PreventiveAlert, change: StatusChange) -> PreventiveAlert | None:
        status_filter = {"$in": [AlertStatus.PENDING, None]} if alert.status == AlertStatus.PENDING else alert.status
        try:
            document = await self._alerts.find_one_and_update(
                {"tenant_id": tenant_id, "id": alert.id, "status": status_filter, "scheduling": None},
                {
                    "$set": {
                        "status": change.status,
                        "is_active": change.status in {AlertStatus.PENDING, AlertStatus.IN_REVIEW},
                    },
                    "$push": {"history": change.model_dump(mode="json")},
                },
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            return None
        return PreventiveAlert.model_validate(document) if document else None

    async def claim_scheduling(self, tenant_id: str, alert_id: str, payload: dict) -> str | None:
        now = datetime.now(timezone.utc)
        lease = str(uuid4())
        result = await self._alerts.update_one(
            {
                "tenant_id": tenant_id,
                "id": alert_id,
                "appointment_id": None,
                "status": {"$nin": [AlertStatus.ATTENDED, AlertStatus.DISMISSED]},
                "$or": [
                    {"scheduling": None},
                    {"scheduling.payload": payload, "scheduling.expires_at": {"$lte": now}},
                ],
            },
            {"$set": {"scheduling": {"payload": payload, "lease": lease, "expires_at": now + timedelta(seconds=30)}}},
        )
        return lease if result.modified_count else None

    async def finish_scheduling(
        self, tenant_id: str, alert_id: str, lease: str, appointment_id: UUID, actor: str, payload: dict,
    ) -> PreventiveAlert | None:
        change = StatusChange(
            status=AlertStatus.ATTENDED, changed_at=datetime.now(timezone.utc), changed_by=actor,
            reason="Service appointment scheduled",
        )
        document = await self._alerts.find_one_and_update(
            {"tenant_id": tenant_id, "id": alert_id, "scheduling.lease": lease},
            {
                "$set": {
                    "appointment_id": str(appointment_id), "status": AlertStatus.ATTENDED, "is_active": False,
                    "appointment_request": payload,
                },
                "$push": {"history": change.model_dump(mode="json")},
                "$unset": {"scheduling": ""},
            },
            return_document=ReturnDocument.AFTER,
        )
        return PreventiveAlert.model_validate(document) if document else None

    async def release_scheduling(self, tenant_id: str, alert_id: str, lease: str, retry_only: bool) -> None:
        criteria = {"tenant_id": tenant_id, "id": alert_id, "scheduling.lease": lease}
        update = (
            {"$set": {"scheduling.expires_at": datetime.now(timezone.utc)}}
            if retry_only else {"$unset": {"scheduling": ""}}
        )
        await self._alerts.update_one(criteria, update)
