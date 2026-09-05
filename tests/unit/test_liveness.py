import os

import cv2
import numpy as np

from black_ice_common.liveness import (
    LivenessOnnxEngine,
    assess_liveness,
    chroma_std,
    is_probably_live,
    laplacian_sharpness,
)


def _sample_image():
    import insightface

    path = os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")
    return cv2.imread(path)


def _full_image_bbox(image: np.ndarray) -> tuple[float, float, float, float]:
    h, w = image.shape[:2]
    return (0.0, 0.0, float(w), float(h))


def test_sharp_real_photo_passes():
    assert is_probably_live(_sample_image())


def test_heavily_blurred_photo_is_flagged():
    image = _sample_image()
    blurred = cv2.GaussianBlur(image, (51, 51), 0)
    assert laplacian_sharpness(blurred) < laplacian_sharpness(image)
    assert not is_probably_live(blurred)


def test_flat_monochrome_crop_has_low_chroma_std():
    """A flat printed/replayed patch (uniform color) should score much lower on
    chroma variance than a real photo with natural skin-tone variation."""
    flat = np.full((100, 100, 3), (120, 110, 100), dtype=np.uint8)
    real = _sample_image()
    assert chroma_std(flat) < chroma_std(real)
    assert not is_probably_live(flat)


def _build_toy_liveness_onnx(path: str) -> None:
    """A tiny hand-built 3-class ONNX classifier (no training framework
    needed) purely to verify LivenessOnnxEngine's crop/preprocessing/
    inference/softmax plumbing — NOT a claim that this is a real trained
    anti-spoofing model. Only class index 2 (LivenessOnnxEngine.LIVE_CLASS_INDEX)
    responds to input, driven by the mean red channel: index 2's logit is
    `mean(R)*5 - 2`, indices 0/1 stay at 0 — so a bright-red crop pushes most
    softmax mass onto index 2 (deterministic, checkable "live" response) and
    a dark crop pushes it away."""
    import onnx
    from onnx import TensorProto, helper

    input_size = 8
    weight = np.zeros((3, 3), dtype=np.float32)
    weight[2, 2] = 5.0  # BGR channel index 2 is R (no BGR->RGB swap in score()) -> logit[2]
    bias = np.array([0.0, 0.0, -2.0], dtype=np.float32)

    pooled = helper.make_node("GlobalAveragePool", ["input"], ["pooled"])
    reshaped = helper.make_node("Reshape", ["pooled", "reshape_shape"], ["reshaped"])
    matmul = helper.make_node("MatMul", ["reshaped", "weight"], ["logits"])
    add = helper.make_node("Add", ["logits", "bias"], ["output"])

    graph = helper.make_graph(
        [pooled, reshaped, matmul, add],
        "toy_liveness",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, input_size, input_size])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 3])],
        initializer=[
            helper.make_tensor("weight", TensorProto.FLOAT, [3, 3], weight.flatten()),
            helper.make_tensor("bias", TensorProto.FLOAT, [3], bias),
            helper.make_tensor("reshape_shape", TensorProto.INT64, [2], [1, 3]),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, path)


def _uniform_frame(color_bgr: tuple[int, int, int], size: int = 32) -> np.ndarray:
    frame = np.zeros((size, size, 3), dtype=np.uint8)
    frame[:, :] = color_bgr
    return frame


def test_liveness_onnx_engine_plumbing(tmp_path):
    model_path = str(tmp_path / "toy_liveness.onnx")
    _build_toy_liveness_onnx(model_path)
    engine = LivenessOnnxEngine(model_path, input_size=8)

    bright_red = _uniform_frame((0, 0, 255))  # BGR -> R channel maxed
    dark = _uniform_frame((0, 0, 0))
    bbox = (8.0, 8.0, 24.0, 24.0)

    red_score = engine.score(bright_red, bbox)
    dark_score = engine.score(dark, bbox)
    assert red_score > 0.8
    assert dark_score < 0.2
    assert red_score > dark_score


def test_assess_liveness_prefers_onnx_engine_when_configured(tmp_path):
    model_path = str(tmp_path / "toy_liveness.onnx")
    _build_toy_liveness_onnx(model_path)
    engine = LivenessOnnxEngine(model_path, input_size=8)

    bright_red = _uniform_frame((0, 0, 255))
    bbox = (8.0, 8.0, 24.0, 24.0)

    result = assess_liveness(bright_red, bbox, onnx_engine=engine)
    assert result.method == "onnx"
    assert result.is_live is True
    assert result.onnx_score is not None


def test_assess_liveness_falls_back_to_heuristic_without_engine():
    image = _sample_image()
    result = assess_liveness(image, _full_image_bbox(image))
    assert result.method == "heuristic"
    assert result.sharpness is not None
    assert result.chroma_std is not None


def test_assess_liveness_rejects_degenerate_bbox():
    image = _sample_image()
    result = assess_liveness(image, (10.0, 10.0, 10.0, 10.0))  # zero-area bbox
    assert result.is_live is False
    assert result.method == "degenerate-bbox"


def test_real_liveness_model_scores_real_face_as_live():
    """Live-verifies the bundled trained model (not the heuristic, not a toy
    graph) against a real face crop — ml/models/minifasnet_v2.onnx must exist
    and actually classify a genuine photo as live."""
    from insightface.app import FaceAnalysis

    model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ml", "models", "minifasnet_v2.onnx")
    if not os.path.exists(model_path):
        import pytest

        pytest.skip("ml/models/minifasnet_v2.onnx not present in this checkout")

    app = FaceAnalysis(providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    image = _sample_image()
    faces = app.get(image)
    assert faces, "expected insightface to find at least one face in t1.jpg"

    engine = LivenessOnnxEngine(model_path)
    x1, y1, x2, y2 = faces[0].bbox
    result = assess_liveness(image, (x1, y1, x2, y2), onnx_engine=engine)

    assert result.method == "onnx"
    assert result.onnx_score > 0.9  # a genuine photo should score confidently live
    assert result.is_live is True
