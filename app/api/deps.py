from fastapi import HTTPException, Request, status
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository


def get_timescale_repo(request: Request) -> TimescaleRepository:
    """Dependency injecting the TimescaleRepository from application state."""
    repo = getattr(request.app.state, "timescale_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TimescaleDB repository is unavailable",
        )
    return repo


def get_mongo_repo(request: Request) -> MongoRepository:
    """Dependency injecting the MongoRepository from application state."""
    repo = getattr(request.app.state, "mongo_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB repository is unavailable",
        )
    return repo


def get_current_tenant_id(request: Request) -> str:
    """Extract authenticated tenant ID from header or development fallback."""
    # 1. Header forwarded by API Gateway / Edge proxy
    tenant_id = request.headers.get("X-Tenant-ID")
    if tenant_id and tenant_id.strip():
        return tenant_id.strip()

    # 2. In local development fallback to standard dev tenant
    return "00000000-0000-0000-0000-000000000001"
