import time

import pytest
import requests.exceptions
import responses


@pytest.fixture()
def db_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    import black_ice_common.config as config

    config.settings.database_url = f"sqlite:///{tmp_path}/alerting_test.db"

    import black_ice_common.db as db

    db.engine = db.create_engine(config.settings.database_url)
    db.SessionLocal = db.sessionmaker(bind=db.engine)
    db.init_db()
    return db


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@responses.activate
def test_fire_alert_delivers_to_matching_enabled_rule(db_module):
    db = db_module
    with db.SessionLocal() as session:
        session.add(db.AlertRule(event_type="access_denied", camera_id="cam-lobby", webhook_url="http://hook.test/a"))
        session.commit()

    responses.post("http://hook.test/a", json={"ok": True}, status=200)

    from black_ice_common.alerting import fire_alert

    fire_alert("access_denied", camera_id="cam-lobby", identity_id="id-1")

    assert _wait_for(lambda: len(responses.calls) == 1)
    body = responses.calls[0].request.body
    assert b"access_denied" in body
    assert b"cam-lobby" in body


@responses.activate
def test_fire_alert_skips_disabled_and_non_matching_rules(db_module):
    db = db_module
    with db.SessionLocal() as session:
        session.add(db.AlertRule(event_type="access_denied", camera_id="cam-lobby", webhook_url="http://hook.test/disabled", enabled=False))
        session.add(db.AlertRule(event_type="access_denied", camera_id="cam-vault", webhook_url="http://hook.test/other-camera"))
        session.add(db.AlertRule(event_type="camera_offline", camera_id="cam-lobby", webhook_url="http://hook.test/other-event"))
        session.commit()

    from black_ice_common.alerting import fire_alert

    fire_alert("access_denied", camera_id="cam-lobby", identity_id="id-1")

    time.sleep(0.2)
    assert len(responses.calls) == 0


@responses.activate
def test_fire_alert_wildcard_rule_matches_any_camera(db_module):
    db = db_module
    with db.SessionLocal() as session:
        session.add(db.AlertRule(event_type="camera_offline", camera_id=None, webhook_url="http://hook.test/wildcard"))
        session.commit()

    responses.post("http://hook.test/wildcard", json={"ok": True}, status=200)

    from black_ice_common.alerting import fire_alert

    fire_alert("camera_offline", camera_id="cam-any")

    assert _wait_for(lambda: len(responses.calls) == 1)


@responses.activate
def test_fire_alert_survives_webhook_failure(db_module):
    db = db_module
    with db.SessionLocal() as session:
        session.add(db.AlertRule(event_type="access_denied", camera_id=None, webhook_url="http://hook.test/broken"))
        session.commit()

    responses.post("http://hook.test/broken", body=requests.exceptions.ConnectionError("refused"))

    from black_ice_common.alerting import fire_alert

    fire_alert("access_denied", camera_id="cam-lobby", identity_id="id-1")
    assert _wait_for(lambda: len(responses.calls) == 1)
