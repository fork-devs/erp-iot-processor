import os
from app.core.config import Settings


def test_default_settings():
    settings = Settings()
    assert settings.SERVER_PORT == 8088
    assert settings.ENVIRONMENT == "dev"
    assert "localhost:9092" in settings.kafka_broker_list
    assert settings.KAFKA_TELEMETRY_TOPIC == "telemetry.raw"
    assert settings.KAFKA_DLQ_TOPIC == "telemetry.dlq"
    assert "postgresql://postgres:postgres@localhost:5432/erp_telemetry" == settings.timescale_dsn
    assert settings.MONGO_DB == "iot_diagnostics"


def test_custom_environment_settings(monkeypatch):
    monkeypatch.setenv("SERVER_PORT", "9090")
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("KAFKA_BROKERS", "broker1:9092,broker2:9092")

    settings = Settings()
    assert settings.SERVER_PORT == 9090
    assert settings.ENVIRONMENT == "prod"
    assert settings.kafka_broker_list == ["broker1:9092", "broker2:9092"]
