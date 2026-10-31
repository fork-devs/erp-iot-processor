from functools import lru_cache
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    # Server settings
    ENVIRONMENT: str = Field(default="dev", description="Runtime environment (dev, staging, prod)")
    SERVER_PORT: int = Field(default=8088, description="HTTP server listening port")
    LOG_LEVEL: str = Field(default="INFO", description="Structured JSON logging level")

    # Kafka Consumer settings
    KAFKA_BROKERS: str = Field(default="localhost:9092", description="Comma-separated Kafka brokers")
    KAFKA_GROUP_ID: str = Field(default="erp-iot-processor-group", description="Consumer group ID")
    KAFKA_TELEMETRY_TOPIC: str = Field(default="telemetry.raw", description="Raw telemetry input topic")
    KAFKA_DLQ_TOPIC: str = Field(default="telemetry.dlq", description="Dead letter queue topic")
    KAFKA_ALERTS_TOPIC: str = Field(default="iot.alerts", description="Topic to publish diagnostic alerts for analytics")
    KAFKA_BATCH_SIZE: int = Field(default=100, description="Max batch size before processing flush")
    KAFKA_BATCH_TIMEOUT_MS: int = Field(default=500, description="Max batch wait timeout in milliseconds")
    KAFKA_AUTO_OFFSET_RESET: str = Field(default="latest", description="Offset reset policy (earliest, latest)")

    # TimescaleDB settings
    TIMESCALE_HOST: str = Field(default="localhost", description="TimescaleDB / PostgreSQL host")
    TIMESCALE_PORT: int = Field(default=5432, description="TimescaleDB / PostgreSQL port")
    TIMESCALE_DB: str = Field(default="erp_telemetry", description="Database name")
    TIMESCALE_USER: str = Field(default="postgres", description="Database user")
    TIMESCALE_PASSWORD: str = Field(default="postgres", description="Database password")
    TIMESCALE_POOL_MIN: int = Field(default=2, description="Minimum asyncpg connection pool size")
    TIMESCALE_POOL_MAX: int = Field(default=10, description="Maximum asyncpg connection pool size")

    # MongoDB settings
    MONGO_URI: str = Field(default="mongodb://localhost:27017", description="MongoDB connection string URI")
    MONGO_DB: str = Field(default="iot_diagnostics", description="MongoDB database name")

    # Security settings
    JWT_SECRET_KEY: str = Field(default="development-secret-key-32-bytes-min!!", description="JWT validation key")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def kafka_broker_list(self) -> List[str]:
        return [b.strip() for b in self.KAFKA_BROKERS.split(",") if b.strip()]

    @property
    def timescale_dsn(self) -> str:
        return f"postgresql://{self.TIMESCALE_USER}:{self.TIMESCALE_PASSWORD}@{self.TIMESCALE_HOST}:{self.TIMESCALE_PORT}/{self.TIMESCALE_DB}"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
