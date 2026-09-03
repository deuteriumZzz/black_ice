"""Per-camera multi-face tracker (SORT-style: IoU association + Kalman prediction,
via norfair) — spec's "Tracking" component. Kept as a library used in-process by
the detect service rather than its own Kafka-hop microservice: it needs frame-to-
frame state for a single camera, which is exactly the kind of tight coupling that
makes a network hop pure overhead.

Detection still runs on every consumed frame (cheap). What this buys is skipping
the *embedding* call (the expensive step) for a track that's already been embedded
recently — spec's "frame sampling + tracking between detections."
"""
import numpy as np
from norfair import Detection, Tracker


def _bbox_from_points(points: np.ndarray) -> tuple[float, float, float, float]:
    (x1, y1), (x2, y2) = points[0], points[1]
    return float(x1), float(y1), float(x2), float(y2)


def _iou(box1: tuple, box2: tuple) -> float:
    xa1, ya1, xa2, ya2 = box1
    xb1, yb1, xb2, yb2 = box2
    ix1, iy1 = max(xa1, xb1), max(ya1, yb1)
    ix2, iy2 = min(xa2, xb2), min(ya2, yb2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _iou_distance(detection, tracked_object) -> float:
    return 1.0 - _iou(_bbox_from_points(detection.points), _bbox_from_points(tracked_object.estimate))


class CameraTracker:
    def __init__(self, embed_interval_frames: int = 15, max_age: int = 30, distance_threshold: float = 0.7):
        self.tracker = Tracker(
            distance_function=_iou_distance,
            distance_threshold=distance_threshold,
            hit_counter_max=max_age,
            initialization_delay=0,  # report a track from its first frame — an access
            # decision can't wait several frames for norfair's default confirmation delay
        )
        self.embed_interval_frames = embed_interval_frames
        self._last_embedded_frame: dict[int, int] = {}
        self._frame_idx = 0

    def update(self, detections: list[tuple[np.ndarray, np.ndarray | None, float]]):
        """detections: [(bbox[4], kps[5,2]|None, det_score), ...] for the current frame.
        Returns [(track_id, bbox, kps, det_score, due_for_embed), ...]."""
        self._frame_idx += 1
        norfair_dets = []
        for bbox, kps, score in detections:
            points = np.array([[bbox[0], bbox[1]], [bbox[2], bbox[3]]])
            norfair_dets.append(
                Detection(points=points, scores=np.array([score, score]), data={"bbox": bbox, "kps": kps, "det_score": score})
            )

        tracked = self.tracker.update(detections=norfair_dets)

        results = []
        for obj in tracked:
            if obj.last_detection is None:
                continue
            data = obj.last_detection.data
            due = obj.id not in self._last_embedded_frame or (
                self._frame_idx - self._last_embedded_frame[obj.id] >= self.embed_interval_frames
            )
            if due:
                self._last_embedded_frame[obj.id] = self._frame_idx
            results.append((obj.id, data["bbox"], data["kps"], data["det_score"], due))
        return results
