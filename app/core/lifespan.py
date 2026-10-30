from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
import asyncpg
from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings
from app.repositories.mongo_repo import MongoRepository
from app.repositories.timescale_repo import TimescaleRepository
from app.services.kafka_consumer import KafkaConsumerWorker
from app.services.processor_service import ProcessorService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI application lifespan manager for resource allocation and graceful shutdown."""
    settings = get_settings()
    logger.info(f"Starting {settings.ENVIRONMENT} erp-iot-processor on port {settings.SERVER_PORT}...")

    # 1. Initialize TimescaleDB pool & repository
    timescale_pool = None
    timescale_repo = TimescaleRepository()
    try:
        timescale_pool = await asyncpg.create_pool(
            dsn=settings.timescale_dsn,
            min_size=settings.TIMESCALE_POOL_MIN,
            max_size=settings.TIMESCALE_POOL_MAX,
            command_timeout=10,
        )
        timescale_repo.set_pool(timescale_pool)
        await timescale_repo.init_schema()
        logger.info("TimescaleDB connection pool initialized successfully")
    except Exception as e:
        logger.warning(f"TimescaleDB connection deferred (will retry upon readyz check): {e}")

    # 2. Initialize MongoDB client & repository
    mongo_client = None
    mongo_repo = MongoRepository()
    try:
        mongo_client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=3000)
        mongo_repo.set_client(mongo_client, settings.MONGO_DB)
        await mongo_repo.init_indices()
        logger.info("MongoDB client and collection indices initialized successfully")
    except Exception as e:
        logger.warning(f"MongoDB connection deferred (will retry upon readyz check): {e}")

    # 3. Initialize Services and Kafka Consumer Worker
    processor_service = ProcessorService(timescale_repo=timescale_repo, mongo_repo=mongo_repo)
    kafka_worker = KafkaConsumerWorker(processor_service=processor_service, settings=settings)

    try:
        await kafka_worker.start()
    except Exception as e:
        logger.warning(f"Kafka consumer start deferred (broker unreachable): {e}")

    # Store objects on application state for dependency injection
    app.state.timescale_pool = timescale_pool
    app.state.timescale_repo = timescale_repo
    app.state.mongo_client = mongo_client
    app.state.mongo_repo = mongo_repo
    app.state.processor_service = processor_service
    app.state.kafka_worker = kafka_worker

    yield

    # Graceful Shutdown
    logger.info("Shutting down erp-iot-processor resources...")
    try:
        await kafka_worker.stop()
    except Exception as e:
        logger.error(f"Error stopping Kafka worker during shutdown: {e}")

    if timescale_pool:
        try:
            await timescale_pool.close()
            logger.info("TimescaleDB pool closed")
        except Exception as e:
            logger.error(f"Error closing TimescaleDB pool: {e}")

    if mongo_client:
        try:
            mongo_client.close()
            logger.info("MongoDB client disconnected")
        except Exception as e:
            logger.error(f"Error closing MongoDB client: {e}")

    logger.info("erp-iot-processor shutdown complete")
