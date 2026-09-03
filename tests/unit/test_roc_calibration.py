import numpy as np

from ml.eval.roc_calibration import eer_threshold, far_frr_curve, genuine_impostor_scores


def test_genuine_impostor_scores_separates_pairs_correctly():
    embeddings = {
        "alice": [np.array([1.0, 0.0]), np.array([0.99, 0.14])],  # near-identical
        "bob": [np.array([0.0, 1.0])],  # orthogonal to alice
    }
    genuine, impostor = genuine_impostor_scores(embeddings)
    assert len(genuine) == 1  # C(2,2) pairs within alice
    assert len(impostor) == 2  # 2 alice vectors x 1 bob vector
    assert genuine[0] > 0.9  # alice's two vectors are near-identical
    assert all(abs(s) < 0.2 for s in impostor)  # near-orthogonal to bob


def test_far_frr_move_in_opposite_directions_as_threshold_rises():
    rng = np.random.default_rng(0)
    genuine = rng.normal(loc=0.8, scale=0.05, size=200)  # genuine pairs score high
    impostor = rng.normal(loc=0.1, scale=0.05, size=200)  # impostor pairs score low

    curve = far_frr_curve(genuine, impostor, n_points=50)
    _, far_low, frr_low = curve[0]  # threshold = -1: accept everything
    _, far_high, frr_high = curve[-1]  # threshold = +1: reject everything

    assert far_low == 1.0 and frr_low == 0.0
    assert far_high == 0.0 and frr_high == 1.0


def test_eer_threshold_lands_between_the_two_populations():
    rng = np.random.default_rng(1)
    genuine = rng.normal(loc=0.8, scale=0.05, size=500)
    impostor = rng.normal(loc=0.1, scale=0.05, size=500)

    curve = far_frr_curve(genuine, impostor, n_points=500)
    threshold, eer = eer_threshold(curve)

    assert 0.1 < threshold < 0.8
    assert eer < 0.05, "well-separated populations should have a low equal-error-rate"
