import logging
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError
from app.domain.models import DiagnosticAlert, VehicleTwinState
from app.repositories.preventive_alerts import PreventiveAlertRepository

logger = logging.getLogger(__name__)


class MongoRepository:
    """Repository managing vehicle twins and diagnostic alerts in MongoDB."""

    def __init__(self, client: Optional[AsyncIOMotorClient] = None, db_name: str = "iot_diagnostics"):
        self._client = client
        self._db_name = db_name
        self._db: Optional[AsyncIOMotorDatabase] = client[db_name] if client else None

    def set_client(self, client: AsyncIOMotorClient, db_name: str = "iot_diagnostics") -> None:
        self._client = client
        self._db_name = db_name
        self._db = client[db_name]

    def preventive_alerts(self) -> PreventiveAlertRepository:
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        return PreventiveAlertRepository(self._db.diagnostic_alerts)

    async def init_indices(self) -> None:
        """Ensure collection indices for efficient lookups."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        # Unique composite index on vehicle_twins
        await self._db.vehicle_twins.create_index(
            [("tenant_id", 1), ("vehicle_id", 1)],
            unique=True,
            name="idx_tenant_vehicle_unique",
        )
        await self._db.diagnostic_alerts.create_index(
            [("tenant_id", 1), ("id", 1)], name="idx_alerts_tenant_id",
        )
        await self._db.diagnostic_alerts.create_index(
            [("tenant_id", 1), ("vehicle_id", 1), ("code", 1)],
            unique=True,
            partialFilterExpression={"is_active": True},
            name="idx_active_alert_per_vehicle_code",
        )
        await self._db.diagnostic_alerts.create_index(
            [("tenant_id", 1), ("vehicle_id", 1), ("code", 1), ("event_history.telemetry_id", 1)],
            unique=True,
            partialFilterExpression={"event_history.telemetry_id": {"$exists": True}},
            name="idx_telemetry_occurrence_unique",
        )
        # Search index on diagnostic_alerts
        await self._db.diagnostic_alerts.create_index(
            [("tenant_id", 1), ("vehicle_id", 1), ("timestamp", -1)],
            name="idx_alerts_tenant_vehicle_time",
        )

    async def upsert_vehicle_twin(self, twin: VehicleTwinState) -> None:
        """Upsert current diagnostic twin state for a vehicle."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        doc = twin.model_dump(mode="json")
        await self._db.vehicle_twins.update_one(
            {"tenant_id": twin.tenant_id, "vehicle_id": twin.vehicle_id},
            {"$set": doc},
            upsert=True,
        )

    async def get_vehicle_twin(self, tenant_id: str, vehicle_id: str) -> Optional[VehicleTwinState]:
        """Fetch the current diagnostic twin state for a vehicle."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        doc = await self._db.vehicle_twins.find_one({"tenant_id": tenant_id, "vehicle_id": vehicle_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return VehicleTwinState.model_validate(doc)

    async def save_alerts(self, alerts: List[DiagnosticAlert], telemetry_id: str) -> int:
        """Group occurrences of the same active condition and deduplicate telemetry retries."""
        if not alerts:
            return 0
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")

        inserted = 0
        collection = self._db.diagnostic_alerts
        for alert in alerts:
            doc = alert.model_dump(mode="json")
            identity = {key: doc[key] for key in ("tenant_id", "vehicle_id", "code")}
            occurrence_query = {**identity, "event_history.telemetry_id": telemetry_id}
            query = {
                **identity,
                "$or": [
                    {"is_active": True},
                    {"is_active": {"$exists": False}, "status": {"$in": [None, "PENDING", "IN_REVIEW"]}},
                ],
            }
            occurrence = {
                "telemetry_id": telemetry_id, "detected_at": doc["timestamp"],
                "severity": doc["severity"], "sensor_values": doc["sensor_values"],
            }
            use_existing_history = {"$ifNull": ["$event_history", []]}
            initial = {
                key: {"$ifNull": [f"${key}", {"$literal": value}]}
                for key, value in doc.items()
            }
            update = [{"$set": {
                **initial,
                "is_active": True,
                "status": {"$ifNull": ["$status", "PENDING"]},
                "event_history": {"$cond": [
                    {"$in": [{"$literal": telemetry_id}, {"$ifNull": ["$event_history.telemetry_id", []]}]},
                    use_existing_history,
                    {"$concatArrays": [use_existing_history, {"$literal": [occurrence]}]},
                ]},
            }}]
            for attempt in range(2):
                try:
                    previous = await collection.find_one_and_update(
                        query, update, sort=[("is_active", -1), ("timestamp", -1)], upsert=True,
                    )
                except DuplicateKeyError:
                    if await collection.find_one(occurrence_query, {"_id": 1}):
                        break
                    if attempt == 1:
                        raise
                else:
                    inserted += previous is None
                    break
        return inserted

    async def get_recent_alerts(self, tenant_id: str, vehicle_id: str, limit: int = 50) -> List[DiagnosticAlert]:
        """Query historical alerts for a vehicle sorted by newest first."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        cursor = (
            self._db.diagnostic_alerts.find({"tenant_id": tenant_id, "vehicle_id": vehicle_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(DiagnosticAlert.model_validate(doc))
        return results

    async def get_paginated_alerts(
        self,
        tenant_id: str,
        vehicle_id: str,
        page: int = 0,
        size: int = 20,
        severity: Optional[str] = None,
    ) -> List[DiagnosticAlert]:
        """Query historical alerts for a vehicle with pagination and optional severity filter."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")

        filter_doc: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "vehicle_id": vehicle_id,
        }
        if severity:
            filter_doc["severity"] = severity.upper()

        offset = max(0, page) * size
        cursor = (
            self._db.diagnostic_alerts.find(filter_doc)
            .sort("timestamp", -1)
            .skip(offset)
            .limit(size)
        )
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(DiagnosticAlert.model_validate(doc))
        return results

    async def get_registration_alerts(
        self,
        tenant_id: str,
        registration_id: str,
        page: int = 0,
        size: int = 20,
    ) -> List[DiagnosticAlert]:
        """Query historical alerts for a device registration with pagination."""
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")

        filter_doc: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "$or": [
                {"vehicle_id": registration_id},
                {"device_id": registration_id},
                {"registration_id": registration_id},
            ],
        }
        offset = max(0, page) * size
        cursor = (
            self._db.diagnostic_alerts.find(filter_doc)
            .sort("timestamp", -1)
            .skip(offset)
            .limit(size)
        )
        results = []
        async for doc in cursor:
            doc.pop("_id", None)
            results.append(DiagnosticAlert.model_validate(doc))
        return results

    async def health_check(self) -> bool:
        """Verify MongoDB connectivity by executing ping command."""
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception as e:
            logger.warning(f"MongoDB health check failed: {e}")
            return False
