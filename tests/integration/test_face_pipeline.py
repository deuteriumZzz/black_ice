"""Exercises the real ONNX models against InsightFace's own bundled sample image.
No network services required (no Kafka/Qdrant/Postgres) — just the ML core."""
import os

import cv2
import numpy as np
import pytest

from black_ice_common.detection import DetectionEngine
from black_ice_common.embedding import EmbeddingEngine


def _sample_image_path() -> str:
    import insightface

    return os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")


@pytest.fixture(scope="module")
def sample_image():
    path = _sample_image_path()
    image = cv2.imread(path)
    assert image is not None, f"could not load {path}"
    return image


@pytest.fixture(scope="module")
def detector():
    return DetectionEngine()


@pytest.fixture(scope="module")
def embedder():
    return EmbeddingEngine()


def test_detects_multiple_faces(sample_image, detector):
    results = detector.detect(sample_image)
    assert len(results) >= 1
    bbox, kps, score = results[0]
    assert score > 0.5
    assert kps is not None and kps.shape == (5, 2)


def test_embedding_is_unit_vector(sample_image, detector, embedder):
    bbox, kps, score = detector.detect(sample_image)[0]
    vec = embedder.embed(sample_image, kps)
    assert vec.shape == (512,)
    assert abs(np.linalg.norm(vec) - 1.0) < 1e-3


def test_same_face_matches_itself(sample_image, detector, embedder):
    bbox, kps, score = detector.detect(sample_image)[0]
    v1 = embedder.embed(sample_image, kps)
    v2 = embedder.embed(sample_image, kps)
    assert np.dot(v1, v2) > 0.99
