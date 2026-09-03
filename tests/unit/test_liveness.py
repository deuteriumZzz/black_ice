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
    """A tiny hand-built ONNX classifier (no training framework needed) purely to
    verify LivenessOnnxEngine's preprocessing/inference/output-parsing plumbing —
    NOT a claim that this is a real trained anti-spoofing model. It computes
    sigmoid(mean(R channel) * 4 - 2), so a bright-red input scores high and a
    dark input scores low — a deterministic, checkable response."""
    import onnx
    from onnx import TensorProto, helper

    input_size = 8
    weight = np.array([[4.0], [0.0], [0.0]], dtype=np.float32)  # only the R channel matters
    bias = np.array([-2.0], dtype=np.float32)

    pooled = helper.make_node("GlobalAveragePool", ["input"], ["pooled"])
    reshaped = helper.make_node("Reshape", ["pooled", "reshape_shape"], ["reshaped"])
    matmul = helper.make_node("MatMul", ["reshaped", "weight"], ["logit"])
    add = helper.make_node("Add", ["logit", "bias"], ["biased"])
    sigmoid = helper.make_node("Sigmoid", ["biased"], ["output"])

    graph = helper.make_graph(
        [pooled, reshaped, matmul, add, sigmoid],
        "toy_liveness",
        [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, input_size, input_size])],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1])],
        initializer=[
            helper.make_tensor("weight", TensorProto.FLOAT, [3, 1], weight.flatten()),
            helper.make_tensor("bias", TensorProto.FLOAT, [1], bias),
            helper.make_tensor("reshape_shape", TensorProto.INT64, [2], [1, 3]),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    onnx.save(model, path)


def test_liveness_onnx_engine_plumbing(tmp_path):
    model_path = str(tmp_path / "toy_liveness.onnx")
    _build_toy_liveness_onnx(model_path)
    engine = LivenessOnnxEngine(model_path, input_size=8)

    bright_red = np.zeros((8, 8, 3), dtype=np.uint8)
    bright_red[:, :, 2] = 255  # BGR -> R channel maxed
    dark = np.zeros((8, 8, 3), dtype=np.uint8)

    red_score = engine.score(bright_red)
    dark_score = engine.score(dark)
    assert red_score > 0.8
    assert dark_score < 0.2
    assert red_score > dark_score


def test_assess_liveness_prefers_onnx_engine_when_configured(tmp_path):
    model_path = str(tmp_path / "toy_liveness.onnx")
    _build_toy_liveness_onnx(model_path)
    engine = LivenessOnnxEngine(model_path, input_size=8)

    bright_red = np.zeros((8, 8, 3), dtype=np.uint8)
    bright_red[:, :, 2] = 255

    result = assess_liveness(bright_red, onnx_engine=engine)
    assert result.method == "onnx"
    assert result.is_live is True
    assert result.onnx_score is not None


def test_assess_liveness_falls_back_to_heuristic_without_engine():
    result = assess_liveness(_sample_image())
    assert result.method == "heuristic"
    assert result.sharpness is not None
    assert result.chroma_std is not None
