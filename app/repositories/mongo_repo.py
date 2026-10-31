import logging
from typing import Any, Dict, List, Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.domain.models import DiagnosticAlert, VehicleTwinState

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

    async def save_alerts(self, alerts: List[DiagnosticAlert]) -> int:
        """Persist emitted diagnostic alerts into the historical alert log."""
        if not alerts:
            return 0
        if self._db is None:
            raise RuntimeError("MongoRepository database is not initialized")
        docs: List[Dict[str, Any]] = [a.model_dump(mode="json") for a in alerts]
        result = await self._db.diagnostic_alerts.insert_many(docs)
        return len(result.inserted_ids)

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
