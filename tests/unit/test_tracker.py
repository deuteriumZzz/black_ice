import numpy as np

from services.tracking.tracker import CameraTracker


def _synthetic_frame(offset: float = 0.0):
    """Two synthetic faces, far enough apart that IoU-matching can't confuse them."""
    return [
        (np.array([10.0 + offset, 10.0, 60.0 + offset, 60.0]), None, 0.9),
        (np.array([200.0 + offset, 200.0, 250.0 + offset, 250.0]), None, 0.9),
    ]


def test_new_tracks_are_due_for_embedding():
    tracker = CameraTracker(embed_interval_frames=5)
    results = tracker.update(_synthetic_frame())
    assert len(results) == 2
    assert all(due for *_, due in results)


def test_track_id_persists_and_sampling_skips_embedding():
    tracker = CameraTracker(embed_interval_frames=3)
    first = tracker.update(_synthetic_frame())
    ids_first = sorted(tid for tid, *_ in first)

    second = tracker.update(_synthetic_frame(offset=1.0))  # tiny motion, same identity
    ids_second = sorted(tid for tid, *_ in second)
    assert ids_second == ids_first
    assert all(due is False for *_, due in second), "shouldn't re-embed before embed_interval_frames elapses"

    third = tracker.update(_synthetic_frame(offset=2.0))
    assert all(due is False for *_, due in third)

    fourth = tracker.update(_synthetic_frame(offset=3.0))  # frame 4 >= embed_interval_frames(3) since track start
    assert any(due is True for *_, due in fourth)
