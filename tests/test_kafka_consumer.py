import asyncio
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.domain.models import GPSLocation, OBDData, TelemetryPacket
from app.services.kafka_consumer import KafkaConsumerWorker
from app.services.processor_service import ProcessorService


@pytest.fixture
def sample_packet() -> TelemetryPacket:
    return TelemetryPacket(
        tenant_id="00000000-0000-0000-0000-000000000001",
        vehicle_id="11111111-1111-1111-1111-111111111111",
        device_id="OBD-DONGLE-01",
        timestamp=datetime.now(timezone.utc),
        location=GPSLocation(latitude=-12.0464, longitude=-77.0428),
        obd=OBDData(engine_rpm=6500, speed_kmh=80.0, coolant_temp_c=120, dtcs=["P0300"]),
    )


@pytest.mark.asyncio
async def test_processor_service_batch(sample_packet: TelemetryPacket):
    mock_timescale = AsyncMock()
    mock_timescale.insert_batch = AsyncMock(return_value=1)

    mock_mongo = AsyncMock()
    mock_mongo.upsert_vehicle_twin = AsyncMock()
    mock_mongo.save_alerts = AsyncMock(return_value=2)

    service = ProcessorService(timescale_repo=mock_timescale, mongo_repo=mock_mongo)
    ts_count, alert_count = await service.process_batch([sample_packet])

    assert ts_count == 1
    assert alert_count > 0  # Emits overheat, overrev, and misfire
    mock_timescale.insert_batch.assert_awaited_once()
    mock_mongo.upsert_vehicle_twin.assert_awaited_once()
    mock_mongo.save_alerts.assert_awaited_once()


@pytest.mark.asyncio
async def test_kafka_consumer_valid_and_dlq_routing(sample_packet: TelemetryPacket):
    mock_service = AsyncMock()
    mock_service.process_batch = AsyncMock(return_value=(1, 1))

    # Prepare 1 valid message and 1 malformed message
    valid_payload = sample_packet.model_dump(mode="json")
    valid_bytes = json.dumps(valid_payload).encode("utf-8")
    malformed_bytes = b'{"corrupted": json'

    mock_valid_msg = MagicMock()
    mock_valid_msg.value = valid_bytes
    mock_valid_msg.topic = "telemetry.raw"
    mock_valid_msg.partition = 0
    mock_valid_msg.offset = 101

    mock_invalid_msg = MagicMock()
    mock_invalid_msg.value = malformed_bytes
    mock_invalid_msg.topic = "telemetry.raw"
    mock_invalid_msg.partition = 0
    mock_invalid_msg.offset = 102

    mock_consumer = AsyncMock()
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()
    mock_consumer.commit = AsyncMock()

    # getmany returns batch on first call, then raises CancelledError to stop loop
    call_count = 0

    async def mock_getmany(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"tp-0": [mock_valid_msg, mock_invalid_msg]}
        raise asyncio.CancelledError()

    mock_consumer.getmany = AsyncMock(side_effect=mock_getmany)

    mock_producer = AsyncMock()
    mock_producer.start = AsyncMock()
    mock_producer.stop = AsyncMock()
    mock_producer.send_and_wait = AsyncMock()

    worker = KafkaConsumerWorker(
        processor_service=mock_service,
        consumer=mock_consumer,
        dlq_producer=mock_producer,
    )

    worker._running = True
    await worker._consume_loop()

    # Verify service processed the 1 valid packet
    mock_service.process_batch.assert_awaited_once()
    processed_packets = mock_service.process_batch.await_args[0][0]
    assert len(processed_packets) == 1
    assert processed_packets[0].vehicle_id == sample_packet.vehicle_id

    # Verify DLQ received the 1 invalid packet
    mock_producer.send_and_wait.assert_awaited_once()
    dlq_topic = mock_producer.send_and_wait.await_args[0][0]
    dlq_data = json.loads(mock_producer.send_and_wait.await_args[0][1].decode("utf-8"))
    assert dlq_topic == "telemetry.dlq"
    assert dlq_data["offset"] == 102

    # Verify consumer committed offsets
    mock_consumer.commit.assert_awaited_once()
