"""Synchronous ad-hoc detection+embedding for /enroll and /identify — a single
uploaded image, not the camera stream. The stream path (services/detect + embed)
is async over Kafka; this is the interactive path, and both share the same engines."""
import numpy as np

from black_ice_common.config import settings
from black_ice_common.detection import DetectionEngine
from black_ice_common.embedding import EmbeddingEngine
from black_ice_common.liveness import LivenessOnnxEngine

_detector: DetectionEngine | None = None
_embedder: EmbeddingEngine | None = None
_shadow_embedder: EmbeddingEngine | None = None
_liveness_engine: LivenessOnnxEngine | None = None
_liveness_engine_loaded = False


def _engines() -> tuple[DetectionEngine, EmbeddingEngine]:
    global _detector, _embedder
    if _detector is None:
        _detector = DetectionEngine()
        _embedder = EmbeddingEngine()
    return _detector, _embedder


def shadow_embedder() -> EmbeddingEngine | None:
    """None unless shadow-mode is enabled — /enroll uses this to also embed into
    the shadow gallery (settings.shadow_collection_name) with the candidate model,
    so shadow decisions are comparable against enrollments made through the same
    endpoint, not a stale/partial gallery."""
    global _shadow_embedder
    if _shadow_embedder is None and settings.shadow_embedding_enabled:
        _shadow_embedder = EmbeddingEngine(pack=settings.shadow_embedding_pack)
    return _shadow_embedder


def liveness_engine() -> LivenessOnnxEngine | None:
    """None unless LIVENESS_ONNX_MODEL_PATH is configured — assess_liveness()
    falls back to the classical heuristic in that case."""
    global _liveness_engine, _liveness_engine_loaded
    if not _liveness_engine_loaded:
        if settings.liveness_onnx_model_path:
            _liveness_engine = LivenessOnnxEngine(settings.liveness_onnx_model_path)
        _liveness_engine_loaded = True
    return _liveness_engine


def largest_face(image_bgr: np.ndarray):
    """Returns (bbox, kps, det_score, embedding) for the largest face, or None."""
    detector, embedder = _engines()
    detections = detector.detect(image_bgr)
    if not detections:
        return None
    bbox, kps, det_score = max(detections, key=lambda d: (d[0][2] - d[0][0]) * (d[0][3] - d[0][1]))
    if kps is None:
        return None
    embedding = embedder.embed(image_bgr, kps)
    return bbox, kps, det_score, embedding
