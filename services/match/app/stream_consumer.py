import logging
import threading

import numpy as np
from pybreaker import CircuitBreaker, CircuitBreakerError

from black_ice_common.access_rules import is_access_allowed
from black_ice_common.alerting import fire_alert
from black_ice_common.config import settings
from black_ice_common.decisioning import evaluate_embedding
from black_ice_common.kafka_io import get_consumer, iter_messages
from black_ice_common.metrics import MATCH_DECISIONS, MATCH_LATENCY
from black_ice_common.schemas import EmbeddingMsg
from black_ice_common.tracing import extract_kafka_context, init_tracing
from services.match.app.ws import live_feed

log = logging.getLogger("match.stream")

# Trips after N consecutive failures against Qdrant/Postgres and fails fast for a
# cooldown window instead of piling up latency on a dependency that's already down.
breaker = CircuitBreaker(fail_max=settings.breaker_fail_max, reset_timeout=settings.breaker_reset_timeout_s)


@breaker
def _search_and_log(msg: EmbeddingMsg) -> dict:
    return evaluate_embedding(
        np.array(msg.embedding),
        msg.camera_id,
        frame_id=msg.frame_id,
        track_id=msg.track_id,
        model_version="primary",
        access_check=is_access_allowed,
    )


def _status_for(result: dict) -> str:
    if not result["matched"]:
        return "IDENTITY UNKNOWN"
    if result["access_granted"] is False:
        return "ACCESS DENIED"
    return "ACCESS GRANTED"


def _handle(msg: EmbeddingMsg) -> None:
    with MATCH_LATENCY.time():
        try:
            result = _search_and_log(msg)
        except CircuitBreakerError:
            log.error("circuit open: Qdrant/Postgres unavailable, dropping embedding for camera %s", msg.camera_id)
            MATCH_DECISIONS.labels(camera_id=msg.camera_id, result="error").inc()
            return

    status = _status_for(result)
    MATCH_DECISIONS.labels(camera_id=msg.camera_id, result="confirmed" if result["matched"] else "unknown").inc()
    if status == "ACCESS DENIED":
        fire_alert("access_denied", camera_id=msg.camera_id, identity_id=result["identity_id"], score=result["score"])
    live_feed.publish_threadsafe(
        {
            "status": status,
            "camera_id": msg.camera_id,
            "track_id": msg.track_id,
            "bbox": msg.bbox,
            "match": f"{max(result['score'], 0) * 100:.1f}%",
            "name": result["name"],
        }
    )


def run_stream_consumer() -> None:
    tracer = init_tracing("black-ice-match")
    consumer = get_consumer(settings.consumer_group_match, [settings.topic_embeddings])
    log.info("match stream consumer starting, group=%s", settings.consumer_group_match)
    for kafka_msg in iter_messages(consumer):
        parent_ctx = extract_kafka_context(kafka_msg.headers())
        with tracer.start_as_current_span("match.decide", context=parent_ctx):
            _handle(EmbeddingMsg.from_json(kafka_msg.value()))


def start_background_consumer() -> threading.Thread:
    thread = threading.Thread(target=run_stream_consumer, name="match-stream-consumer", daemon=True)
    thread.start()
    return thread
