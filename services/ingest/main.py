"""One OS process per camera (spec 3.1: CPU-bound video decode doesn't parallelize
across threads under the GIL, so the unit of scale is the process/container, not a
thread inside one). Reads frames and publishes them to Kafka; does no CV work itself.

SOURCE="demo" loops over ml/eval/sample_frames/*.jpg — lets the whole pipeline run
without a webcam or RTSP feed. Point SOURCE at a webcam index ("0"), a video file
path, or an rtsp:// URL to use a real feed.
"""
import glob
import itertools
import logging
import os
import time
import uuid

import cv2

from black_ice_common.config import settings
from black_ice_common.kafka_io import get_producer, produce_json
from black_ice_common.metrics import FRAMES_INGESTED, serve_metrics
from black_ice_common.schemas import FrameMsg
from black_ice_common.tracing import init_tracing, inject_kafka_headers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("ingest")

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "eval", "sample_frames")


def _demo_frames():
    paths = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*.jpg")))
    if not paths:
        raise RuntimeError(f"no demo frames found in {SAMPLE_DIR}")
    for path in itertools.cycle(paths):
        yield cv2.imread(path)


def _capture_frames(source: str):
    cap_source = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(cap_source)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video source: {source}")
    while True:
        ok, frame = cap.read()
        if not ok:
            log.warning("frame read failed, retrying")
            time.sleep(1.0)
            continue
        yield frame


def run() -> None:
    serve_metrics(settings.metrics_port)
    tracer = init_tracing("black-ice-ingest")
    producer = get_producer()
    frame_iter = _demo_frames() if settings.source == "demo" else _capture_frames(settings.source)
    period = 1.0 / settings.ingest_fps

    log.info("ingest starting: camera_id=%s source=%s fps=%s", settings.camera_id, settings.source, settings.ingest_fps)
    for frame in frame_iter:
        start = time.monotonic()
        with tracer.start_as_current_span("ingest.publish_frame"):
            ok, jpg = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            msg = FrameMsg(
                frame_id=str(uuid.uuid4()),
                camera_id=settings.camera_id,
                ts=time.time(),
                jpg_b64=FrameMsg.encode_jpg(jpg.tobytes()),
            )
            produce_json(
                producer, settings.topic_frames, key=settings.camera_id, payload=msg.to_json(),
                headers=inject_kafka_headers(),
            )
            FRAMES_INGESTED.labels(camera_id=settings.camera_id).inc()
            producer.flush(0)

        elapsed = time.monotonic() - start
        time.sleep(max(0.0, period - elapsed))


if __name__ == "__main__":
    run()
