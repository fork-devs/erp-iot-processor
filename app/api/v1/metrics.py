from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

router = APIRouter(tags=["Metrics"])

# Operational Metrics Definitions
TELEMETRY_MESSAGES_PROCESSED_TOTAL = Counter(
    "iot_processor_messages_processed_total",
    "Total number of processed telemetry messages",
    ["status"],
)

DIAGNOSTIC_EVALUATION_LATENCY_SECONDS = Histogram(
    "iot_processor_evaluation_latency_seconds",
    "Diagnostic evaluation latency in seconds",
)

TIMESCALE_INSERT_LATENCY_SECONDS = Histogram(
    "iot_processor_timescale_insert_latency_seconds",
    "TimescaleDB batch insert latency in seconds",
)

MONGO_UPDATE_LATENCY_SECONDS = Histogram(
    "iot_processor_mongo_update_latency_seconds",
    "MongoDB twin upsert and alert save latency in seconds",
)

KAFKA_ALERTS_EMITTED_TOTAL = Counter(
    "iot_processor_alerts_emitted_total",
    "Total number of diagnostic alerts emitted to Kafka",
    ["severity"],
)


@router.get(
    "/metrics",
    response_class=Response,
    include_in_schema=False,
    summary="Prometheus Metrics Scraping Endpoint",
)
async def get_metrics() -> Response:
    """Expose Prometheus formatted operational metrics for monitoring orchestrators."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
