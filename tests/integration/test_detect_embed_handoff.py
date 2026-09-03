"""Regression test for the detect->embed Kafka handoff: detect ships a crop + a
crop-local landmarks + the crop's origin (not the whole frame), and embed must
reconstruct an embedding equivalent to embedding the full frame directly. Caught
a real bug once — too tight a crop margin clips ArcFace's alignment warp and
silently degrades match quality without raising any error."""
import os

import cv2
import numpy as np
import pytest

from black_ice_common.detection import DetectionEngine
from black_ice_common.embedding import EmbeddingEngine
from services.detect.main import _crop_with_margin


@pytest.fixture(scope="module")
def sample_image():
    import insightface

    path = os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")
    image = cv2.imread(path)
    assert image is not None
    return image


@pytest.fixture(scope="module")
def detector():
    return DetectionEngine()


@pytest.fixture(scope="module")
def embedder():
    return EmbeddingEngine()


def test_crop_and_reprojected_kps_preserve_embedding(sample_image, detector, embedder):
    results = detector.detect(sample_image)
    assert len(results) > 1  # sample image is a group photo — exercises several bbox positions

    for bbox, kps, _score in results:
        direct_vec = embedder.embed(sample_image, kps)

        crop, (origin_x, origin_y) = _crop_with_margin(sample_image, bbox)
        local_kps = np.array([[x - origin_x, y - origin_y] for x, y in kps], dtype=np.float32)
        crop_vec = embedder.embed(crop, local_kps)

        similarity = float(np.dot(direct_vec, crop_vec))
        assert similarity > 0.999, f"crop handoff degraded embedding: cosine sim={similarity}"
