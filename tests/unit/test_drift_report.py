import numpy as np

from scripts.drift_report import detect_score_drift, unknown_rate


def test_similar_distributions_do_not_trigger_drift():
    rng = np.random.default_rng(0)
    baseline = rng.normal(loc=0.8, scale=0.05, size=200)
    recent = rng.normal(loc=0.8, scale=0.05, size=200)  # same underlying distribution

    result = detect_score_drift(baseline, recent)
    assert result["insufficient_data"] is False
    assert result["drift_detected"] is False


def test_shifted_distribution_triggers_drift():
    rng = np.random.default_rng(0)
    baseline = rng.normal(loc=0.8, scale=0.05, size=200)
    recent = rng.normal(loc=0.5, scale=0.05, size=200)  # scores dropped hard

    result = detect_score_drift(baseline, recent)
    assert result["drift_detected"] is True
    assert result["recent_mean"] < result["baseline_mean"]


def test_insufficient_data_is_reported_not_silently_ignored():
    result = detect_score_drift(np.array([0.8, 0.81]), np.array([0.5, 0.51]))
    assert result["insufficient_data"] is True


def test_unknown_rate():
    assert unknown_rate([True, True, False, False]) == 0.5
    assert unknown_rate([]) == 0.0
    assert unknown_rate([True, True]) == 0.0
