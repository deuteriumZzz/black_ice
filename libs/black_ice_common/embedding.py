"""Embedding-only wrapper around InsightFace's buffalo_l recognizer (ArcFace).
Takes a crop + 5-point landmarks produced by DetectionEngine and returns a 512-d
L2-normalized embedding — this is the model that actually needs the GPU in prod."""
import os

import numpy as np
from insightface.app.common import Face
from insightface.model_zoo import model_zoo

from black_ice_common.detection import model_dir

_DEFAULT_RECOGNITION_FILENAME = {
    "buffalo_l": "w600k_r50.onnx",  # ResNet50 backbone — primary production model
    "buffalo_s": "w600k_mbf.onnx",  # MobileFaceNet backbone — smaller/faster, shadow-mode candidate
}


class EmbeddingEngine:
    def __init__(self, pack: str = "buffalo_l", recognition_filename: str | None = None, model_path: str | None = None):
        """`model_path` overrides everything else (an arbitrary onnx file — e.g. a
        shadow-mode candidate model not shipped as an InsightFace pack at all).
        Otherwise resolves `recognition_filename` inside `pack`'s model dir,
        defaulting to each known pack's actual recognition-model filename."""
        if model_path is None:
            recognition_filename = recognition_filename or _DEFAULT_RECOGNITION_FILENAME[pack]
            model_path = os.path.join(model_dir(pack), recognition_filename)
        self.model = model_zoo.get_model(model_path, providers=["CPUExecutionProvider"])

    def embed(self, image_bgr: np.ndarray, kps: np.ndarray) -> np.ndarray:
        face = Face(bbox=None, kps=np.array(kps, dtype=np.float32), det_score=1.0)
        self.model.get(image_bgr, face)
        return face.normed_embedding
