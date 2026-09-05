import datetime

import pytest


@pytest.fixture()
def db_module(tmp_path, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

    import black_ice_common.config as config

    config.settings.database_url = f"sqlite:///{tmp_path}/access_rules_test.db"

    import black_ice_common.db as db

    db.engine = db.create_engine(config.settings.database_url)
    db.SessionLocal = db.sessionmaker(bind=db.engine)
    db.init_db()
    return db


def _make_identity(db, session) -> str:
    identity = db.Identity(name="Neo", consent_given=True)
    session.add(identity)
    session.commit()
    return identity.id


def test_no_rules_means_denied(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)

    from black_ice_common.access_rules import is_access_allowed

    assert is_access_allowed(identity_id, "cam-lobby") is False


def test_all_cameras_all_day_rule_allows(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(db.AccessRule(identity_id=identity_id, camera_id=None))
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    assert is_access_allowed(identity_id, "cam-lobby") is True
    assert is_access_allowed(identity_id, "cam-vault") is True


def test_rule_scoped_to_other_camera_denies(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(db.AccessRule(identity_id=identity_id, camera_id="cam-lobby"))
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    assert is_access_allowed(identity_id, "cam-lobby") is True
    assert is_access_allowed(identity_id, "cam-vault") is False


def test_disabled_rule_is_ignored(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(db.AccessRule(identity_id=identity_id, camera_id=None, enabled=False))
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    assert is_access_allowed(identity_id, "cam-lobby") is False


def test_weekday_window_gates_access(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(db.AccessRule(identity_id=identity_id, camera_id=None, weekdays="mon,tue,wed,thu,fri"))
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    monday_9am = datetime.datetime(2026, 9, 7, 9, 0)  # a Monday
    saturday_9am = datetime.datetime(2026, 9, 5, 9, 0)  # a Saturday
    assert is_access_allowed(identity_id, "cam-lobby", now=monday_9am) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=saturday_9am) is False


def test_time_window_gates_access(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(
            db.AccessRule(
                identity_id=identity_id,
                camera_id=None,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0),
            )
        )
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    during = datetime.datetime(2026, 9, 7, 12, 0)
    before = datetime.datetime(2026, 9, 7, 7, 0)
    assert is_access_allowed(identity_id, "cam-lobby", now=during) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=before) is False


def test_overnight_window_gates_access(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(
            db.AccessRule(
                identity_id=identity_id,
                camera_id=None,
                start_time=datetime.time(22, 0),
                end_time=datetime.time(6, 0),
            )
        )
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    late_night = datetime.datetime(2026, 9, 4, 23, 0)  # Friday 23:00
    early_morning = datetime.datetime(2026, 9, 5, 2, 0)  # Saturday 02:00 - still the same overnight shift
    midday = datetime.datetime(2026, 9, 5, 12, 0)
    assert is_access_allowed(identity_id, "cam-lobby", now=late_night) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=early_morning) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=midday) is False


def test_overnight_window_weekday_matches_shift_start_day(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(
            db.AccessRule(
                identity_id=identity_id,
                camera_id=None,
                weekdays="fri",
                start_time=datetime.time(22, 0),
                end_time=datetime.time(6, 0),
            )
        )
        session.commit()

    from black_ice_common.access_rules import is_access_allowed

    friday_night = datetime.datetime(2026, 9, 4, 23, 0)  # Friday 23:00 - shift starts Friday
    saturday_tail = datetime.datetime(2026, 9, 5, 2, 0)  # Saturday 02:00 - still Friday's shift
    saturday_night = datetime.datetime(2026, 9, 5, 23, 0)  # Saturday 23:00 - a *different* shift, not "fri"
    assert is_access_allowed(identity_id, "cam-lobby", now=friday_night) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=saturday_tail) is True
    assert is_access_allowed(identity_id, "cam-lobby", now=saturday_night) is False


def test_identity_deletion_cascades_to_rules(db_module):
    db = db_module
    with db.SessionLocal() as session:
        identity_id = _make_identity(db, session)
        session.add(db.AccessRule(identity_id=identity_id, camera_id=None))
        session.commit()

        session.delete(session.get(db.Identity, identity_id))
        session.commit()

        assert session.query(db.AccessRule).filter(db.AccessRule.identity_id == identity_id).count() == 0
