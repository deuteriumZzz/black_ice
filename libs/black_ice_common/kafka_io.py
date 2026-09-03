"""Thin confluent-kafka wrappers. Business logic never touches these objects directly —
services import produce_json/iter_messages, not Producer/Consumer, so the processing
functions stay unit-testable without a broker."""
from collections.abc import Iterator

from confluent_kafka import Consumer, KafkaError, Message, Producer

from black_ice_common.config import settings


def get_producer() -> Producer:
    return Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})


def produce_json(
    producer: Producer, topic: str, key: str, payload: bytes, headers: list[tuple[str, bytes]] | None = None
) -> None:
    producer.produce(topic, key=key.encode("utf-8"), value=payload, headers=headers)
    producer.poll(0)


def get_consumer(group_id: str, topics: list[str]) -> Consumer:
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "latest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe(topics)
    return consumer


def iter_messages(consumer: Consumer, timeout: float = 1.0) -> Iterator[Message]:
    """Blocks the calling process/pod in a poll loop — this is the horizontal unit of
    scale (per-pod consumer in a group), not a thread, per the GIL note in the spec."""
    while True:
        msg = consumer.poll(timeout)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            raise RuntimeError(msg.error())
        yield msg
