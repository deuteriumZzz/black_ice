from black_ice_common.db import AuditLog


def test_shadow_report_counts_agreements_and_disagreements(match_client):
    import black_ice_common.db as db_module
    import scripts.shadow_report as report_module

    report_module.SessionLocal = db_module.SessionLocal

    with db_module.SessionLocal() as session:
        # agree: both matched the same identity
        session.add(AuditLog(frame_id="f1", track_id=1, model_version="primary", matched=True, identity_id="alice", score=0.9))
        session.add(AuditLog(frame_id="f1", track_id=1, model_version="buffalo_s", matched=True, identity_id="alice", score=0.8))

        # disagree: primary matched, shadow did not
        session.add(AuditLog(frame_id="f2", track_id=2, model_version="primary", matched=True, identity_id="bob", score=0.7))
        session.add(AuditLog(frame_id="f2", track_id=2, model_version="buffalo_s", matched=False, identity_id=None, score=0.2))

        # disagree: shadow matched, primary did not
        session.add(AuditLog(frame_id="f3", track_id=3, model_version="primary", matched=False, identity_id=None, score=0.3))
        session.add(AuditLog(frame_id="f3", track_id=3, model_version="buffalo_s", matched=True, identity_id="carol", score=0.85))

        # no shadow counterpart — must not be counted
        session.add(AuditLog(frame_id="f4", track_id=4, model_version="primary", matched=True, identity_id="dave", score=0.9))
        session.commit()

    result = report_module.compare("buffalo_s")

    assert result["compared"] == 3
    assert result["agree"] == 1
    assert result["primary_matched_shadow_did_not"] == 1
    assert result["shadow_matched_primary_did_not"] == 1
    assert abs(result["agreement_rate"] - (1 / 3)) < 1e-9
