"""Webhook delivery for AlertRule matches (spec Phase 1 Milestone 4). Fires in a
daemon thread, not inline — a slow or dead webhook receiver must never add
latency to the match hot path or block scripts/camera_offline_check.py's sweep.

References black_ice_common.db as a module, not by name-imported symbols — same
convention as decisioning.py/access_rules.py, for the same reason (tests patch
db.SessionLocal).
"""
import logging
import threading

import requests

import black_ice_common.db as db
from black_ice_common.config import settings

log = logging.getLogger("black_ice.alerting")


def _deliver(rule_id: str, payload: dict) -> None:
    try:
        requests.post(payload["webhook_url"], json=payload, timeout=settings.alert_webhook_timeout_s)
    except requests.RequestException as exc:
        log.warning("alert webhook delivery failed for rule %s: %s", rule_id, exc)


def fire_alert(event_type: str, camera_id: str | None = None, identity_id: str | None = None, **details) -> list[threading.Thread]:
    """Returns the delivery threads it started (daemon, fire-and-forget from a
    long-running service's point of view — e.g. stream_consumer.py, which just
    discards the list). A short-lived caller that exits right after firing
    (scripts/camera_offline_check.py) MUST join() the returned threads first —
    a daemon thread is killed mid-flight the instant the process exits, so
    without joining, a CronJob's alerts would routinely never actually send.

    ponytail: no rate limiting/cooldown per rule — a flapping identity or
    camera could spawn many delivery threads in a short window. Add a per-rule
    cooldown (e.g. last-fired timestamp on AlertRule) if that becomes real."""
    with db.SessionLocal() as session:
        rules = (
            session.query(db.AlertRule)
            .filter(db.AlertRule.event_type == event_type, db.AlertRule.enabled.is_(True))
            .filter((db.AlertRule.camera_id == camera_id) | (db.AlertRule.camera_id.is_(None)))
            .filter((db.AlertRule.identity_id == identity_id) | (db.AlertRule.identity_id.is_(None)))
            .all()
        )
        matched = [(rule.id, rule.webhook_url) for rule in rules]

    threads = []
    for rule_id, webhook_url in matched:
        payload = {"event_type": event_type, "camera_id": camera_id, "identity_id": identity_id, "webhook_url": webhook_url, **details}
        thread = threading.Thread(target=_deliver, args=(rule_id, payload), daemon=True)
        thread.start()
        threads.append(thread)
    return threads
