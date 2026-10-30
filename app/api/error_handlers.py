import logging
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def create_problem_detail(
    type_uri: str,
    title: str,
    status_code: int,
    detail: str,
    extra: Dict[str, Any] = None,
) -> JSONResponse:
    content = {
        "type": type_uri,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if extra:
        content.update(extra)

    return JSONResponse(
        status_code=status_code,
        content=content,
        media_type="application/problem+json",
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return create_problem_detail(
            type_uri="https://erp-automotive.pe/errors/http-error",
            title="HTTP Error",
            status_code=exc.status_code,
            detail=str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return create_problem_detail(
            type_uri="https://erp-automotive.pe/errors/validation-error",
            title="Unprocessable Entity",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request validation failed",
            extra={"invalid_params": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled server error: {exc}", exc_info=True)
        return create_problem_detail(
            type_uri="https://erp-automotive.pe/errors/internal-server-error",
            title="Internal Server Error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while processing the request",
        )
