"""Shadow-mode evaluation consumer: runs a candidate embedding model's decisions
against its own gallery (never the primary one — different model, different
embedding space) and logs them for offline comparison
(scripts/shadow_report.py) — never broadcasts to the live UI and never feeds the
real access-control outcome. A separate CircuitBreaker means a broken candidate
model can't degrade the primary path."""
import logging
import threading

import numpy as np
from pybreaker import CircuitBreaker, CircuitBreakerError

from black_ice_common.config import settings
from black_ice_common.decisioning import evaluate_embedding
from black_ice_common.kafka_io import get_consumer, iter_messages
from black_ice_common.metrics import MATCH_DECISIONS
from black_ice_common.schemas import EmbeddingMsg
from black_ice_common.tracing import extract_kafka_context, init_tracing

log = logging.getLogger("match.shadow")

breaker = CircuitBreaker(fail_max=settings.breaker_fail_max, reset_timeout=settings.breaker_reset_timeout_s)


@breaker
def _search_and_log(msg: EmbeddingMsg) -> dict:
    return evaluate_embedding(
        np.array(msg.embedding),
        msg.camera_id,
        frame_id=msg.frame_id,
        track_id=msg.track_id,
        model_version=settings.shadow_embedding_pack,
        collection=settings.shadow_collection_name,
        requested_by="shadow",
    )


def _handle(msg: EmbeddingMsg) -> None:
    try:
        result = _search_and_log(msg)
    except CircuitBreakerError:
        log.error("shadow circuit open: dropping shadow embedding for camera %s", msg.camera_id)
        MATCH_DECISIONS.labels(camera_id=msg.camera_id, result="shadow-error").inc()
        return
    MATCH_DECISIONS.labels(camera_id=msg.camera_id, result="shadow-confirmed" if result["matched"] else "shadow-unknown").inc()


def run_shadow_consumer() -> None:
    tracer = init_tracing("black-ice-match-shadow")
    consumer = get_consumer(settings.consumer_group_shadow, [settings.topic_embeddings_shadow])
    log.info("shadow consumer starting, group=%s, model=%s", settings.consumer_group_shadow, settings.shadow_embedding_pack)
    for kafka_msg in iter_messages(consumer):
        parent_ctx = extract_kafka_context(kafka_msg.headers())
        with tracer.start_as_current_span("match.shadow_decide", context=parent_ctx):
            _handle(EmbeddingMsg.from_json(kafka_msg.value()))


def start_background_consumer() -> threading.Thread | None:
    if not settings.shadow_embedding_enabled:
        return None
    thread = threading.Thread(target=run_shadow_consumer, name="match-shadow-consumer", daemon=True)
    thread.start()
    return thread
