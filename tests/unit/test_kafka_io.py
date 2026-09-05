from unittest.mock import MagicMock

import pytest
from confluent_kafka import KafkaError

from black_ice_common.kafka_io import iter_messages


def _error_msg(code: int) -> MagicMock:
    msg = MagicMock()
    err = MagicMock()
    err.code.return_value = code
    msg.error.return_value = err
    return msg


def _ok_msg() -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = None
    return msg


def test_iter_messages_skips_partition_eof():
    consumer = MagicMock()
    consumer.poll.side_effect = [_error_msg(KafkaError._PARTITION_EOF), _ok_msg()]

    it = iter_messages(consumer)
    msg = next(it)
    assert msg.error() is None


def test_iter_messages_skips_unknown_topic_and_keeps_polling():
    """A consumer subscribing before any producer has published to the topic
    (cold start) must not crash — see kafka_io.py's comment for why this is
    treated as transient rather than fatal, unlike other broker errors."""
    consumer = MagicMock()
    consumer.poll.side_effect = [
        _error_msg(KafkaError.UNKNOWN_TOPIC_OR_PART),
        _error_msg(KafkaError.UNKNOWN_TOPIC_OR_PART),
        _ok_msg(),
    ]

    it = iter_messages(consumer)
    msg = next(it)
    assert msg.error() is None
    assert consumer.poll.call_count == 3


def test_iter_messages_raises_on_other_errors():
    consumer = MagicMock()
    consumer.poll.side_effect = [_error_msg(KafkaError._TRANSPORT)]

    with pytest.raises(RuntimeError):
        next(iter_messages(consumer))


def test_iter_messages_skips_none_polls():
    consumer = MagicMock()
    consumer.poll.side_effect = [None, None, _ok_msg()]

    msg = next(iter_messages(consumer))
    assert msg.error() is None
