from typing import Any, Dict
from fastapi import APIRouter, Depends, Response, status
from app.api.deps import get_mongo_repo, get_timescale_repo
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository

router = APIRouter(tags=["Health Probes"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def liveness() -> Dict[str, str]:
    """Liveness probe indicating the HTTP server process is running."""
    return {"status": "UP", "service": "erp-iot-processor"}


@router.get("/readyz")
async def readiness(
    response: Response,
    timescale_repo: TimescaleRepository = Depends(get_timescale_repo),
    mongo_repo: MongoRepository = Depends(get_mongo_repo),
) -> Dict[str, Any]:
    """Readiness probe evaluating TimescaleDB and MongoDB operational availability."""
    timescale_ok = await timescale_repo.health_check()
    mongo_ok = await mongo_repo.health_check()

    all_ready = timescale_ok and mongo_ok
    if not all_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "UP" if all_ready else "DOWN",
        "service": "erp-iot-processor",
        "components": {
            "timescaledb": "UP" if timescale_ok else "DOWN",
            "mongodb": "UP" if mongo_ok else "DOWN",
        },
    }
