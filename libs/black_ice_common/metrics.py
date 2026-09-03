from prometheus_client import Counter, Histogram, start_http_server

FRAMES_INGESTED = Counter("black_ice_frames_ingested_total", "Frames published by ingest", ["camera_id"])
FACES_DETECTED = Counter("black_ice_faces_detected_total", "Faces detected", ["camera_id"])
FACES_EMBEDDED = Counter("black_ice_faces_embedded_total", "Faces embedded", ["camera_id"])
MATCH_DECISIONS = Counter("black_ice_match_decisions_total", "Access decisions", ["camera_id", "result"])

DETECT_LATENCY = Histogram("black_ice_detect_seconds", "Per-frame detection latency")
EMBED_LATENCY = Histogram("black_ice_embed_seconds", "Per-face embedding latency")
MATCH_LATENCY = Histogram("black_ice_match_seconds", "Per-face vector-search + decision latency")


def serve_metrics(port: int) -> None:
    start_http_server(port)
