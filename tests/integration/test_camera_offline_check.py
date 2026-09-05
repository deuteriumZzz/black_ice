import datetime
import time

import responses


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@responses.activate
def test_offline_camera_is_detected_and_alerted(match_client, monkeypatch):
    import black_ice_common.config as config
    import black_ice_common.db as db_module
    import scripts.camera_offline_check as check_module

    monkeypatch.setattr(config.settings, "camera_offline_threshold_s", 60.0)
    responses.post("http://hook.test/offline", json={"ok": True}, status=200)

    now = datetime.datetime.utcnow()
    with db_module.SessionLocal() as session:
        stale = db_module.Camera(camera_id="cam-stale", name="Stale", source="0", last_seen_at=now - datetime.timedelta(minutes=5))
        fresh = db_module.Camera(camera_id="cam-fresh", name="Fresh", source="0", last_seen_at=now - datetime.timedelta(seconds=5))
        never_seen_new = db_module.Camera(camera_id="cam-new", name="New", source="0", created_at=now)
        session.add_all([stale, fresh, never_seen_new])
        session.add(db_module.AlertRule(event_type="camera_offline", camera_id=None, webhook_url="http://hook.test/offline"))
        session.commit()

    offline_count = check_module.check_offline_cameras(now=now)

    assert offline_count == 1
    assert _wait_for(lambda: len(responses.calls) == 1)


def test_disabled_camera_is_never_flagged(match_client, monkeypatch):
    import black_ice_common.config as config
    import black_ice_common.db as db_module
    import scripts.camera_offline_check as check_module

    monkeypatch.setattr(config.settings, "camera_offline_threshold_s", 60.0)

    now = datetime.datetime.utcnow()
    with db_module.SessionLocal() as session:
        disabled = db_module.Camera(
            camera_id="cam-disabled", name="Disabled", source="0",
            last_seen_at=now - datetime.timedelta(hours=1), enabled=False,
        )
        session.add(disabled)
        session.commit()

    assert check_module.check_offline_cameras(now=now) == 0
