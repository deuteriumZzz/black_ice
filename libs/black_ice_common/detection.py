"""Detection-only wrapper around InsightFace's buffalo_l detector (RetinaFace/SCRFD),
used standalone by the detect service and by an equivalent one on the embed side.

We load the ONNX file directly via model_zoo instead of the full FaceAnalysis app —
FaceAnalysis.get() asserts a detection model is present and always runs every module
in the pack, which is exactly the coupling stage-2 splits detect and embed to avoid.
"""
import os

import numpy as np
from insightface.app import FaceAnalysis
from insightface.model_zoo import model_zoo

MODEL_PACK = "buffalo_l"


def model_dir(pack: str = MODEL_PACK) -> str:
    root = os.path.expanduser("~/.insightface/models")
    path = os.path.join(root, pack)
    if not os.path.isdir(path):
        # One-time download of the full pack; each engine below then loads only
        # the single ONNX file it needs.
        FaceAnalysis(name=pack, providers=["CPUExecutionProvider"])
    return path


class DetectionEngine:
    def __init__(self, det_size: tuple[int, int] = (640, 640)):
        det_path = os.path.join(model_dir(), "det_10g.onnx")
        self.model = model_zoo.get_model(det_path, providers=["CPUExecutionProvider"])
        self.model.prepare(ctx_id=-1, input_size=det_size)

    def detect(self, image_bgr: np.ndarray) -> list[tuple[np.ndarray, np.ndarray | None, float]]:
        """Returns [(bbox[4], kps[5,2] | None, det_score), ...]."""
        bboxes, kpss = self.model.detect(image_bgr, max_num=0, metric="default")
        results = []
        for i in range(bboxes.shape[0]):
            bbox = bboxes[i, 0:4]
            det_score = float(bboxes[i, 4])
            kps = kpss[i] if kpss is not None else None
            results.append((bbox, kps, det_score))
        return results
