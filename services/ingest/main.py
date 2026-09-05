"""One OS process per camera (spec 3.1: CPU-bound video decode doesn't parallelize
across threads under the GIL, so the unit of scale is the process/container, not a
thread inside one). Reads frames and publishes them to Kafka; does no CV work itself.

SOURCE="demo" loops over ml/eval/sample_frames/*.jpg — lets the whole pipeline run
without a webcam or RTSP feed, and skips the camera-registry lookup below entirely
(no match service needed to run the demo path). Any other value means this ingest
is a real camera: at startup it fetches its own source/fps from match's camera
registry (GET /cameras/{camera_id}/config, see Phase 1 Milestone 2) rather than
from SOURCE/INGEST_FPS env vars directly — those two env vars are only the
fallback used when the registry lookup itself fails to start (see _resolve_config).
"""
import glob
import itertools
import logging
import os
import threading
import time
import uuid

import cv2
import requests

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


def _auth_headers() -> dict[str, str]:
    return {"X-API-Key": settings.ingest_api_key}


def _resolve_config(camera_id: str) -> tuple[str, float]:
    """Fetches (source, ingest_fps) from match's camera registry. Retries a
    handful of times for transient failures (match still starting up) but
    fails hard on 404/403 — a misconfigured camera silently capturing the
    wrong source, or a disabled one capturing at all, is worse than a
    container that crashes loudly and gets noticed. 403 can now also mean a
    wrong/missing INGEST_API_KEY (see rbac.ROLES's "ingest" role), not just a
    disabled camera — the error message below reflects whichever the response
    body actually says, instead of assuming it's always the camera."""
    url = f"{settings.match_api_url}/cameras/{camera_id}/config"
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=_auth_headers(), timeout=5)
        except requests.RequestException as exc:
            last_error = exc
            log.warning("camera config fetch failed (attempt %d/3): %s", attempt + 1, exc)
            time.sleep(2**attempt)
            continue
        if resp.status_code == 404:
            raise RuntimeError(f"camera '{camera_id}' is not registered — add it via the admin console first")
        if resp.status_code in (401, 403):
            detail = resp.json().get("detail", resp.text)
            raise RuntimeError(f"camera '{camera_id}' config request denied ({resp.status_code}): {detail}")
        resp.raise_for_status()
        data = resp.json()
        return data["source"], data["ingest_fps"]
    raise RuntimeError(f"could not reach camera registry at {url} after 3 attempts: {last_error}")


def _heartbeat_loop(camera_id: str) -> None:
    url = f"{settings.match_api_url}/cameras/{camera_id}/heartbeat"
    while True:
        try:
            requests.post(url, headers=_auth_headers(), timeout=5)
        except requests.RequestException as exc:
            log.warning("heartbeat failed: %s", exc)
        time.sleep(settings.heartbeat_interval_s)


def run() -> None:
    serve_metrics(settings.metrics_port)
    tracer = init_tracing("black-ice-ingest")
    producer = get_producer()

    if settings.source == "demo":
        frame_iter = _demo_frames()
        resolved_source, fps = "demo", settings.ingest_fps
    else:
        resolved_source, fps = _resolve_config(settings.camera_id)
        frame_iter = _capture_frames(resolved_source)
        threading.Thread(target=_heartbeat_loop, args=(settings.camera_id,), daemon=True).start()

    period = 1.0 / fps

    log.info("ingest starting: camera_id=%s source=%s fps=%s", settings.camera_id, resolved_source, fps)
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
