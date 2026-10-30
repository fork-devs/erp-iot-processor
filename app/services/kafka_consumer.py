import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, List, Optional
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.domain.models import TelemetryPacket
from app.services.processor_service import ProcessorService

logger = logging.getLogger(__name__)


class KafkaConsumerWorker:
    """Asynchronous Kafka Consumer Group worker processing telemetry streams with DLQ routing."""

    def __init__(
        self,
        processor_service: ProcessorService,
        settings: Optional[Settings] = None,
        consumer: Optional[AIOKafkaConsumer] = None,
        dlq_producer: Optional[AIOKafkaProducer] = None,
    ):
        self._service = processor_service
        self._settings = settings or get_settings()
        self._consumer = consumer
        self._producer = dlq_producer
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Initialize consumer and producer connections, starting background loop."""
        if self._consumer is None:
            self._consumer = AIOKafkaConsumer(
                self._settings.KAFKA_TELEMETRY_TOPIC,
                bootstrap_servers=self._settings.kafka_broker_list,
                group_id=self._settings.KAFKA_GROUP_ID,
                enable_auto_commit=False,
                auto_offset_reset=self._settings.KAFKA_AUTO_OFFSET_RESET,
            )
        if self._producer is None:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._settings.kafka_broker_list,
            )

        await self._consumer.start()
        await self._producer.start()
        self._running = True
        logger.info(
            f"Kafka consumer started on topic '{self._settings.KAFKA_TELEMETRY_TOPIC}' with group '{self._settings.KAFKA_GROUP_ID}'"
        )
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        """Signal consumer to stop, cancel task, and cleanly disconnect."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._consumer:
            try:
                await self._consumer.stop()
            except Exception as e:
                logger.warning(f"Error stopping Kafka consumer: {e}")

        if self._producer:
            try:
                await self._producer.stop()
            except Exception as e:
                logger.warning(f"Error stopping Kafka DLQ producer: {e}")

        logger.info("Kafka consumer and DLQ producer stopped gracefully")

    async def _consume_loop(self) -> None:
        """Main polling and batch processing loop."""
        while self._running:
            try:
                if not self._consumer:
                    break
                # Fetch batch from assigned partitions
                batch_dict = await self._consumer.getmany(
                    timeout_ms=self._settings.KAFKA_BATCH_TIMEOUT_MS,
                    max_records=self._settings.KAFKA_BATCH_SIZE,
                )

                if not batch_dict:
                    await asyncio.sleep(0.05)
                    continue

                valid_packets: List[TelemetryPacket] = []
                for tp, messages in batch_dict.items():
                    for msg in messages:
                        try:
                            payload_str = msg.value.decode("utf-8")
                            data = json.loads(payload_str)
                            packet = TelemetryPacket.model_validate(data)
                            valid_packets.append(packet)
                        except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as err:
                            logger.warning(f"Malformed telemetry packet on offset {msg.offset}: {err}. Routing to DLQ.")
                            await self._route_to_dlq(msg, str(err))

                if valid_packets:
                    try:
                        await self._service.process_batch(valid_packets)
                    except Exception as e:
                        logger.error(f"Error processing telemetry batch: {e}", exc_info=True)
                        # We don't commit offsets on unexpected DB failure so Kafka can retry
                        continue

                # Commit offsets after successful processing and DLQ routing
                await self._consumer.commit()

            except asyncio.CancelledError:
                break
            except Exception as err:
                logger.error(f"Unexpected error in Kafka consume loop: {err}", exc_info=True)
                await asyncio.sleep(1.0)

    async def _route_to_dlq(self, msg: Any, error_detail: str) -> None:
        """Route unparseable or schema-violating payload to dead-letter queue."""
        if not self._producer:
            return
        dlq_event = {
            "error": error_detail,
            "topic": getattr(msg, "topic", self._settings.KAFKA_TELEMETRY_TOPIC),
            "partition": getattr(msg, "partition", 0),
            "offset": getattr(msg, "offset", 0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_payload": getattr(msg, "value", b"").decode("utf-8", "replace"),
        }
        try:
            await self._producer.send_and_wait(
                self._settings.KAFKA_DLQ_TOPIC,
                json.dumps(dlq_event).encode("utf-8"),
            )
        except Exception as e:
            logger.error(f"Failed to route message to DLQ: {e}")
