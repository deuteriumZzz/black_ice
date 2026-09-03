import datetime

import numpy as np

from black_ice_common.db import AuditLog


def test_run_pulls_correct_windows_from_audit_log(match_client):
    """match_client wires db.SessionLocal to a throwaway sqlite db; reused here
    purely for that backend, not the HTTP API."""
    import black_ice_common.db as db_module
    import scripts.drift_report as drift_module

    drift_module.SessionLocal = db_module.SessionLocal

    now = datetime.datetime.utcnow()
    rng = np.random.default_rng(0)

    with db_module.SessionLocal() as session:
        # baseline window: 10-8 days ago, high scores
        for score in rng.normal(loc=0.85, scale=0.03, size=40):
            session.add(AuditLog(ts=now - datetime.timedelta(days=9), matched=True, score=float(score)))
        # recent window: today, noticeably lower scores
        for score in rng.normal(loc=0.55, scale=0.03, size=40):
            session.add(AuditLog(ts=now - datetime.timedelta(hours=2), matched=True, score=float(score)))
        # outside both windows — must not leak into either
        for score in rng.normal(loc=0.99, scale=0.01, size=40):
            session.add(AuditLog(ts=now - datetime.timedelta(days=30), matched=True, score=float(score)))
        session.commit()

    result = drift_module.run(baseline_days_ago=(10, 8), recent_days=1, pushgateway_url=None)

    assert result["insufficient_data"] is False
    assert result["baseline_n"] == 40
    assert result["recent_n"] == 40
    assert result["drift_detected"] is True
    assert result["recent_mean"] < result["baseline_mean"]
