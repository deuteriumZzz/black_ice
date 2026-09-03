"""Kafka consumer-group worker: detection runs on every frame (cheap); the tracker
decides which detections are actually due for the expensive embedding step. Scale
by running more pods in the same consumer group (spec 3.1) — not more threads.
"""
import logging
import time

import cv2
import numpy as np

from black_ice_common.config import settings
from black_ice_common.detection import DetectionEngine
from black_ice_common.kafka_io import get_consumer, get_producer, iter_messages, produce_json
from black_ice_common.metrics import DETECT_LATENCY, FACES_DETECTED, serve_metrics
from black_ice_common.schemas import DetectionMsg, FrameMsg
from black_ice_common.tracing import extract_kafka_context, init_tracing, inject_kafka_headers
from services.tracking.tracker import CameraTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("detect")

CROP_MARGIN = 0.5  # measured: <0.5 clips ArcFace's alignment warp near bbox edges and
# measurably degrades the embedding (cosine sim as low as 0.97 vs the un-cropped face);
# 0.5 empirically gets every test face to >0.999 similarity vs embedding the full frame


def _crop_with_margin(image: np.ndarray, bbox) -> tuple[np.ndarray, tuple[int, int]]:
    """Returns (crop, (origin_x, origin_y)). The origin is shipped alongside the
    crop so embed can re-project landmarks exactly — margins get clamped asymmetrically
    near image edges, so assuming a symmetric margin on the receiving end is wrong."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    x1 = max(0, int(x1 - bw * CROP_MARGIN))
    y1 = max(0, int(y1 - bh * CROP_MARGIN))
    x2 = min(w, int(x2 + bw * CROP_MARGIN))
    y2 = min(h, int(y2 + bh * CROP_MARGIN))
    return image[y1:y2, x1:x2], (x1, y1)


def run() -> None:
    serve_metrics(settings.metrics_port)
    tracer = init_tracing("black-ice-detect")
    detector = DetectionEngine()
    consumer = get_consumer(settings.consumer_group_detect, [settings.topic_frames])
    producer = get_producer()
    trackers: dict[str, CameraTracker] = {}

    log.info("detect worker starting, group=%s", settings.consumer_group_detect)
    for kafka_msg in iter_messages(consumer):
        parent_ctx = extract_kafka_context(kafka_msg.headers())
        with tracer.start_as_current_span("detect.process_frame", context=parent_ctx):
            frame = FrameMsg.from_json(kafka_msg.value())
            image = cv2.imdecode(np.frombuffer(frame.jpg_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue

            with DETECT_LATENCY.time():
                raw_detections = detector.detect(image)
            if raw_detections:
                FACES_DETECTED.labels(camera_id=frame.camera_id).inc(len(raw_detections))

            tracker = trackers.setdefault(
                frame.camera_id,
                CameraTracker(
                    embed_interval_frames=settings.embed_interval_frames,
                    max_age=settings.track_max_age_frames,
                    distance_threshold=settings.track_iou_distance_threshold,
                ),
            )
            tracks = tracker.update(raw_detections)

            for track_id, bbox, kps, det_score, due_for_embed in tracks:
                if not due_for_embed or kps is None:
                    continue
                crop, (origin_x, origin_y) = _crop_with_margin(image, bbox)
                ok, crop_jpg = cv2.imencode(".jpg", crop)
                if not ok:
                    continue
                det_msg = DetectionMsg(
                    frame_id=frame.frame_id,
                    camera_id=frame.camera_id,
                    ts=time.time(),
                    track_id=track_id,
                    bbox=[float(v) for v in bbox],
                    kps=[[float(x) - origin_x, float(y) - origin_y] for x, y in kps],
                    det_score=det_score,
                    crop_jpg_b64=FrameMsg.encode_jpg(crop_jpg.tobytes()),
                )
                produce_json(
                    producer, settings.topic_detections, key=frame.camera_id, payload=det_msg.to_json(),
                    headers=inject_kafka_headers(),
                )


if __name__ == "__main__":
    run()
