"""Liveness / anti-spoofing (spec section 4). Two layers:

1. Classical multi-signal heuristic (`is_probably_live`) — texture (Laplacian
   sharpness) + chroma variance (`YCrCb` std-dev), the same family of features
   real anti-spoofing literature calls "color-texture analysis" (Boulkenafet et
   al.). Genuine signal, but still a heuristic: catches a flat/low-res printed-
   photo or screen replay, nothing more. Off by default
   (`LIVENESS_CHECK_ENABLED=false`) — real false-reject rate on cheap webcams.

2. `LivenessOnnxEngine` — a real plug-in point for a *trained* liveness
   classifier (e.g. MiniFASNet / Silent-Face-Anti-Spoofing converted to ONNX).
   No such model ships here — pulling in a full second framework (most of these
   projects ship as TensorFlow/PyTorch, e.g. `deepface`'s bundled anti-spoofing
   drags in TensorFlow+Keras+pandas and breaks this project's pinned numpy<2 /
   onnxruntime-only stack) is a worse trade than not having a trained model at
   all. This engine runs a plain ONNX classifier through the onnxruntime
   dependency the project already has — point `LIVENESS_ONNX_MODEL_PATH` at a
   converted checkpoint to use it; `assess_liveness` prefers it over the
   heuristic when configured, and falls back otherwise.
"""
from dataclasses import dataclass

import cv2
import numpy as np


def laplacian_sharpness(image_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def chroma_std(image_bgr: np.ndarray) -> float:
    """Mean of the Cr/Cb channel standard deviations. Real skin under normal
    lighting has more natural chroma variation than a printed photo (limited ink
    gamut) or a screen replay (panel color quantization + uniform backlight)."""
    ycrcb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2YCrCb)
    cr, cb = ycrcb[:, :, 1], ycrcb[:, :, 2]
    return float((cr.std() + cb.std()) / 2)


@dataclass
class LivenessResult:
    is_live: bool
    method: str
    sharpness: float | None = None
    chroma_std: float | None = None
    onnx_score: float | None = None


def is_probably_live(image_bgr: np.ndarray, min_sharpness: float = 40.0, min_chroma_std: float = 5.0) -> bool:
    """Both signals must clear their floor — a print/replay flat enough to fool
    one often still fails the other."""
    return laplacian_sharpness(image_bgr) >= min_sharpness and chroma_std(image_bgr) >= min_chroma_std


class LivenessOnnxEngine:
    def __init__(self, model_path: str, input_size: int = 80):
        import onnxruntime as ort

        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size

    def score(self, face_crop_bgr: np.ndarray) -> float:
        """Returns a scalar where higher = more likely live. Preprocessing:
        resize to a square `input_size`, RGB, NCHW, [0, 1] float — the common
        convention for these classifiers; adjust here if a specific converted
        checkpoint expects different normalization."""
        resized = cv2.resize(face_crop_bgr, (self.input_size, self.input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        chw = np.transpose(rgb, (2, 0, 1))[None, ...]
        output = self.session.run(None, {self.input_name: chw})[0]
        return float(np.asarray(output).reshape(-1)[0])


def assess_liveness(
    image_bgr: np.ndarray,
    onnx_engine: LivenessOnnxEngine | None = None,
    onnx_threshold: float = 0.5,
    min_sharpness: float = 40.0,
    min_chroma_std: float = 5.0,
) -> LivenessResult:
    if onnx_engine is not None:
        score = onnx_engine.score(image_bgr)
        return LivenessResult(is_live=score >= onnx_threshold, method="onnx", onnx_score=score)

    sharpness = laplacian_sharpness(image_bgr)
    c_std = chroma_std(image_bgr)
    return LivenessResult(
        is_live=sharpness >= min_sharpness and c_std >= min_chroma_std,
        method="heuristic",
        sharpness=sharpness,
        chroma_std=c_std,
    )
