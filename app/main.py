from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_error_handlers
from app.api.v1.diagnostics import router as diagnostics_router
from app.api.v1.health import router as health_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.telemetry_queries import router as telemetry_queries_router
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.LOG_LEVEL)

app = FastAPI(
    title="DriveOS - ERP IoT Processor Service",
    description="Asynchronous telemetry stream processor, DTC classifier, and vehicle twin manager",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "prod" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "prod" else None,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register RFC 9457 error handlers
register_error_handlers(app)

# Include API routers
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(diagnostics_router)
app.include_router(telemetry_queries_router, prefix="/api/v1/vehicles")
app.include_router(telemetry_queries_router, prefix="/api/v1/iot/vehicles")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "erp-iot-processor",
        "environment": settings.ENVIRONMENT,
        "docs": "/docs" if settings.ENVIRONMENT != "prod" else "disabled",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.SERVER_PORT,
        reload=(settings.ENVIRONMENT == "dev"),
    )
