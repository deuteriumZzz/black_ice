"""Kafka consumer-group worker: crop + landmarks in, 512-d embedding out. This is
the model that actually wants a GPU in prod; scale by adding pods to the group."""
import logging
import time

import cv2
import numpy as np

from black_ice_common.config import settings
from black_ice_common.embedding import EmbeddingEngine
from black_ice_common.kafka_io import get_consumer, get_producer, iter_messages, produce_json
from black_ice_common.metrics import EMBED_LATENCY, FACES_EMBEDDED, serve_metrics
from black_ice_common.schemas import DetectionMsg, EmbeddingMsg
from black_ice_common.tracing import extract_kafka_context, init_tracing, inject_kafka_headers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("embed")


def run() -> None:
    serve_metrics(settings.metrics_port)
    tracer = init_tracing("black-ice-embed")
    embedder = EmbeddingEngine()
    shadow_embedder = EmbeddingEngine(pack=settings.shadow_embedding_pack) if settings.shadow_embedding_enabled else None
    consumer = get_consumer(settings.consumer_group_embed, [settings.topic_detections])
    producer = get_producer()

    log.info("embed worker starting, group=%s, shadow=%s", settings.consumer_group_embed, settings.shadow_embedding_enabled)
    for kafka_msg in iter_messages(consumer):
        parent_ctx = extract_kafka_context(kafka_msg.headers())
        with tracer.start_as_current_span("embed.process_detection", context=parent_ctx):
            det = DetectionMsg.from_json(kafka_msg.value())
            crop_bytes = __import__("base64").b64decode(det.crop_jpg_b64)
            crop = cv2.imdecode(np.frombuffer(crop_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if crop is None:
                continue
            kps = np.array(det.kps, dtype=np.float32)

            with EMBED_LATENCY.time():
                vector = embedder.embed(crop, kps)
            FACES_EMBEDDED.labels(camera_id=det.camera_id).inc()

            emb_msg = EmbeddingMsg(
                frame_id=det.frame_id,
                camera_id=det.camera_id,
                ts=time.time(),
                track_id=det.track_id,
                bbox=det.bbox,
                embedding=vector.tolist(),
            )
            produce_json(
                producer, settings.topic_embeddings, key=det.camera_id, payload=emb_msg.to_json(),
                headers=inject_kafka_headers(),
            )

            if shadow_embedder is not None:
                shadow_vector = shadow_embedder.embed(crop, kps)
                shadow_msg = EmbeddingMsg(
                    frame_id=det.frame_id,
                    camera_id=det.camera_id,
                    ts=time.time(),
                    track_id=det.track_id,
                    bbox=det.bbox,
                    embedding=shadow_vector.tolist(),
                )
                produce_json(
                    producer, settings.topic_embeddings_shadow, key=det.camera_id, payload=shadow_msg.to_json(),
                    headers=inject_kafka_headers(),
                )


if __name__ == "__main__":
    run()
