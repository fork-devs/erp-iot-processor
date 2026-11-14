from uuid import UUID
from fastapi import HTTPException, Header, Request, status

from app.core.security import NIL_UUID, verify_access_token_and_extract_tenant
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


def get_current_tenant_id(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> str:
    """Verify Bearer JWT, extract tenant_id claim, and cross-check optional X-Tenant-ID header."""
    auth_header = authorization or request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Bearer authentication token",
        )

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer authentication token",
        )

    token_tenant_id = verify_access_token_and_extract_tenant(token)

    raw_header_tenant = x_tenant_id or request.headers.get("X-Tenant-ID")
    if raw_header_tenant and raw_header_tenant.strip():
        try:
            header_uuid = UUID(raw_header_tenant.strip())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Tenant-ID header: must be a valid UUID",
            )
        if header_uuid == NIL_UUID or str(header_uuid) != token_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="X-Tenant-ID header does not match authenticated token tenant",
            )

    return token_tenant_id
