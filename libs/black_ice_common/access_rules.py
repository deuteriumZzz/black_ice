"""Access-rule evaluation (spec Phase 1 Milestone 3): default-deny/allow-list — an
identity with zero matching enabled rules is denied. Fail-closed is the correct
default for physical access control (fail-open would mean a newly enrolled face
gets in everywhere until someone remembers to restrict it).

References black_ice_common.db as a module, not by name-imported symbols — same
convention as decisioning.py, for the same reason (tests patch db.SessionLocal).
"""
import datetime

import black_ice_common.db as db

_WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _rule_matches_now(rule: "db.AccessRule", now: datetime.datetime) -> bool:
    # A window's weekday is the day the *shift* started, not the calendar day
    # "now" falls on. For an overnight window (22:00-06:00) checked at 02:00
    # Saturday, the shift started Friday — a "fri"-only rule must still match.
    shift_day = now
    if rule.start_time is not None and rule.end_time is not None:
        start, end, t = rule.start_time, rule.end_time, now.time()
        if start <= end:
            if not (start <= t <= end):
                return False
        elif t >= start:
            pass  # shift started today, still running
        elif t <= end:
            shift_day = now - datetime.timedelta(days=1)  # still in yesterday's overnight tail
        else:
            return False

    if rule.weekdays is not None:
        today = _WEEKDAY_CODES[shift_day.weekday()]
        if today not in {d.strip() for d in rule.weekdays.split(",")}:
            return False
    return True


def is_access_allowed(identity_id: str, camera_id: str, now: datetime.datetime | None = None) -> bool:
    now = now or datetime.datetime.utcnow()
    with db.SessionLocal() as session:
        rules = (
            session.query(db.AccessRule)
            .filter(db.AccessRule.identity_id == identity_id, db.AccessRule.enabled.is_(True))
            .filter((db.AccessRule.camera_id == camera_id) | (db.AccessRule.camera_id.is_(None)))
            .all()
        )
    return any(_rule_matches_now(rule, now) for rule in rules)
