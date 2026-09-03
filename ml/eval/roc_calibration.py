"""FAR/FRR threshold calibration + ROC/DET curve (spec: "Калибровка threshold через
FAR/FRR, построение ROC/DET-кривой"). Needs a labeled face dataset (a directory per
identity, images of that identity inside) — LFW-style layout:

    dataset/
      alice/ a1.jpg a2.jpg
      bob/   b1.jpg b2.jpg

Genuine pairs = same-identity image pairs; impostor pairs = cross-identity pairs.
Run: python ml/eval/roc_calibration.py --dataset /path/to/dataset --out roc.png
"""
import argparse
import itertools
import os

import cv2
import numpy as np

from black_ice_common.detection import DetectionEngine
from black_ice_common.embedding import EmbeddingEngine


def embed_dataset(dataset_dir: str) -> dict[str, list[np.ndarray]]:
    detector = DetectionEngine()
    embedder = EmbeddingEngine()
    embeddings: dict[str, list[np.ndarray]] = {}

    for identity in sorted(os.listdir(dataset_dir)):
        identity_dir = os.path.join(dataset_dir, identity)
        if not os.path.isdir(identity_dir):
            continue
        vectors = []
        for fname in sorted(os.listdir(identity_dir)):
            image = cv2.imread(os.path.join(identity_dir, fname))
            if image is None:
                continue
            detections = detector.detect(image)
            if not detections:
                continue
            bbox, kps, _score = max(detections, key=lambda d: (d[0][2] - d[0][0]) * (d[0][3] - d[0][1]))
            if kps is None:
                continue
            vectors.append(embedder.embed(image, kps))
        if vectors:
            embeddings[identity] = vectors
    return embeddings


def genuine_impostor_scores(embeddings: dict[str, list[np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
    genuine, impostor = [], []
    identities = list(embeddings.keys())

    for vecs in embeddings.values():
        for a, b in itertools.combinations(vecs, 2):
            genuine.append(float(np.dot(a, b)))

    for id_a, id_b in itertools.combinations(identities, 2):
        for a in embeddings[id_a]:
            for b in embeddings[id_b]:
                impostor.append(float(np.dot(a, b)))

    return np.array(genuine), np.array(impostor)


def far_frr_curve(genuine: np.ndarray, impostor: np.ndarray, n_points: int = 200) -> list[tuple[float, float, float]]:
    """Returns [(threshold, FAR, FRR), ...]. FAR = impostor pairs scored >= threshold
    (falsely accepted); FRR = genuine pairs scored < threshold (falsely rejected)."""
    thresholds = np.linspace(-1.0, 1.0, n_points)
    curve = []
    for t in thresholds:
        far = float(np.mean(impostor >= t)) if len(impostor) else 0.0
        frr = float(np.mean(genuine < t)) if len(genuine) else 0.0
        curve.append((float(t), far, frr))
    return curve


def eer_threshold(curve: list[tuple[float, float, float]]) -> tuple[float, float]:
    """Equal Error Rate: the threshold where FAR and FRR are closest."""
    best = min(curve, key=lambda row: abs(row[1] - row[2]))
    return best[0], (best[1] + best[2]) / 2


def plot_curves(curve: list[tuple[float, float, float]], out_path: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    thresholds, far, frr = zip(*curve)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    ax1.plot(thresholds, far, label="FAR")
    ax1.plot(thresholds, frr, label="FRR")
    ax1.set_xlabel("cosine similarity threshold")
    ax1.set_ylabel("error rate")
    ax1.set_title("DET curve")
    ax1.legend()

    ax2.plot(far, [1 - f for f in frr])
    ax2.set_xlabel("FAR")
    ax2.set_ylabel("1 - FRR (TAR)")
    ax2.set_title("ROC curve")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", default="roc.png")
    args = parser.parse_args()

    embeddings = embed_dataset(args.dataset)
    print(f"embedded {sum(len(v) for v in embeddings.values())} images across {len(embeddings)} identities")

    genuine, impostor = genuine_impostor_scores(embeddings)
    print(f"{len(genuine)} genuine pairs, {len(impostor)} impostor pairs")

    curve = far_frr_curve(genuine, impostor)
    threshold, eer = eer_threshold(curve)
    print(f"recommended threshold (EER): {threshold:.3f}  (EER={eer:.4f})")

    plot_curves(curve, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
