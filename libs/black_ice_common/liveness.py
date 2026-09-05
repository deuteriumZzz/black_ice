"""Liveness / anti-spoofing (spec section 4). Two layers:

1. Classical multi-signal heuristic (`is_probably_live`) — texture (Laplacian
   sharpness) + chroma variance (`YCrCb` std-dev), the same family of features
   real anti-spoofing literature calls "color-texture analysis" (Boulkenafet et
   al.). Genuine signal, but still a heuristic: catches a flat/low-res printed-
   photo or screen replay, nothing more. Off by default
   (`LIVENESS_CHECK_ENABLED=false`) — real false-reject rate on cheap webcams.

2. `LivenessOnnxEngine` — a *trained* liveness classifier: MiniFASNetV2 from
   minivision-ai/Silent-Face-Anti-Spoofing, ONNX-converted (bit-equivalent to
   the upstream `.pth`, SHA-256 verified against the upstream checkpoint) so
   it runs on the onnxruntime dependency this project already has, no
   TensorFlow/PyTorch at inference time (e.g. `deepface`'s bundled anti-
   spoofing drags in TensorFlow+Keras+pandas and breaks this project's pinned
   numpy<2 / onnxruntime-only stack — a worse trade). Weights live at
   `ml/models/minifasnet_v2.onnx`; point `LIVENESS_ONNX_MODEL_PATH` at it (or
   a differently-scaled/sized checkpoint of the same architecture family) to
   use it — `assess_liveness` prefers it over the heuristic when configured,
   and falls back otherwise.
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
    """`scale`/`input_size` come from the checkpoint's own filename convention
    (minivision-ai ships `<scale>_<size>x<size>_<arch>.pth`, e.g.
    `2.7_80x80_MiniFASNetV2`) — the crop margin and expected input side. The
    bundled `ml/models/minifasnet_v2.onnx` is that exact 2.7/80 checkpoint;
    the defaults below match it.

    LIVE_CLASS_INDEX=2 was verified empirically, not read off documentation —
    two independent write-ups of this exact model disagreed with each other
    (one claimed output order `[live, print, replay]` i.e. index 0, the
    official upstream repo's own inference script implies index 1 via
    `label == 1: Real Face`) and both turned out wrong for this ONNX export:
    running it against 6 real face crops (insightface's bundled `t1.jpg`)
    consistently put ~99% of the softmax mass on index 2. Re-verify this the
    same way (a handful of real faces, check which index dominates) if this
    model is ever swapped for a different checkpoint or a different
    converter's export of the same one — the ONNX graph's class order isn't
    something to trust from a README.
    """

    LIVE_CLASS_INDEX = 2

    def __init__(self, model_path: str, input_size: int = 80, crop_scale: float = 2.7):
        import onnxruntime as ort

        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size
        self.crop_scale = crop_scale

    def _crop(self, frame_bgr: np.ndarray, bbox_xyxy: tuple[float, float, float, float]) -> np.ndarray:
        """Reproduces minivision-ai's CropImage exactly (src/generate_patches.py):
        a `crop_scale`-times-larger box centered on the face bbox, cropped from
        the *original* frame — the model needs the surrounding context a
        tightly-cropped face box would already have thrown away — then resized
        to a square `input_size`. Out-of-bounds is handled by shifting the box
        inward, not padding, matching the reference implementation."""
        src_h, src_w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = bbox_xyxy
        x, y, box_w, box_h = x1, y1, x2 - x1, y2 - y1

        scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, self.crop_scale))
        new_w, new_h = box_w * scale, box_h * scale
        cx, cy = box_w / 2 + x, box_h / 2 + y

        left, top = cx - new_w / 2, cy - new_h / 2
        right, bottom = cx + new_w / 2, cy + new_h / 2
        if left < 0:
            right -= left
            left = 0
        if top < 0:
            bottom -= top
            top = 0
        if right > src_w - 1:
            left -= right - src_w + 1
            right = src_w - 1
        if bottom > src_h - 1:
            top -= bottom - src_h + 1
            bottom = src_h - 1
        left, top, right, bottom = int(left), int(top), int(right), int(bottom)

        cropped = frame_bgr[top : bottom + 1, left : right + 1]
        return cv2.resize(cropped, (self.input_size, self.input_size))

    def score(self, frame_bgr: np.ndarray, bbox_xyxy: tuple[float, float, float, float]) -> float:
        """Returns P(live) in [0, 1]. BGR in, BGR to the model — the reference
        pipeline never converts to RGB, only scales to [0, 1] (no mean/std
        normalization). The ONNX graph outputs raw logits, not softmax (their
        sum is nowhere near 1) — softmax is applied here, not baked into the
        export."""
        crop = self._crop(frame_bgr, bbox_xyxy)
        chw = np.transpose(crop.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
        logits = np.asarray(self.session.run(None, {self.input_name: chw})[0]).reshape(-1)
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        return float(probs[self.LIVE_CLASS_INDEX])


def assess_liveness(
    frame_bgr: np.ndarray,
    bbox_xyxy: tuple[float, float, float, float],
    onnx_engine: LivenessOnnxEngine | None = None,
    onnx_threshold: float = 0.5,
    min_sharpness: float = 40.0,
    min_chroma_std: float = 5.0,
) -> LivenessResult:
    """Takes the *full* frame plus the face bbox, not a pre-cropped face — the
    ONNX path needs margin around the bbox that a tight crop would already
    have discarded (see LivenessOnnxEngine._crop); the heuristic path derives
    its own tight crop from the same bbox, so both share one call site."""
    x1, y1, x2, y2 = bbox_xyxy
    if x2 <= x1 or y2 <= y1:
        return LivenessResult(is_live=False, method="degenerate-bbox")

    if onnx_engine is not None:
        score = onnx_engine.score(frame_bgr, bbox_xyxy)
        return LivenessResult(is_live=score >= onnx_threshold, method="onnx", onnx_score=score)

    crop = frame_bgr[int(y1) : int(y2), int(x1) : int(x2)]
    sharpness = laplacian_sharpness(crop)
    c_std = chroma_std(crop)
    return LivenessResult(
        is_live=sharpness >= min_sharpness and c_std >= min_chroma_std,
        method="heuristic",
        sharpness=sharpness,
        chroma_std=c_std,
    )
