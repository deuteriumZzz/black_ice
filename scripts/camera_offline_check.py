"""Camera-offline sweep (spec Phase 1 Milestone 4). Meant to run as a K8s
CronJob (infra/k8s/black-ice/templates/camera-offline-cronjob.yaml) or a
cron/systemd-timer in non-k8s deployments — heartbeat staleness (see Camera
model, Milestone 2) is only ever written by ingest's own HTTP call, nothing
else in this codebase polls it, so without this sweep a dead camera is only
noticed by a human looking at the admin-ui.

References black_ice_common.db as a module, not by name-imported symbols — see
libs/black_ice_common/decisioning.py's docstring for why (tests patch
db.SessionLocal after this module is first imported).
"""
import datetime
import logging

import black_ice_common.db as db
from black_ice_common.alerting import fire_alert
from black_ice_common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("camera_offline_check")


def check_offline_cameras(now: datetime.datetime | None = None) -> int:
    now = now or datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(seconds=settings.camera_offline_threshold_s)
    offline_count = 0
    pending_deliveries = []
    with db.SessionLocal() as session:
        cameras = session.query(db.Camera).filter(db.Camera.enabled.is_(True)).all()
        for camera in cameras:
            never_seen_but_old_enough = camera.last_seen_at is None and camera.created_at < cutoff
            gone_stale = camera.last_seen_at is not None and camera.last_seen_at < cutoff
            if never_seen_but_old_enough or gone_stale:
                offline_count += 1
                pending_deliveries += fire_alert("camera_offline", camera_id=camera.camera_id, last_seen_at=str(camera.last_seen_at))
    # this is a one-shot script (K8s CronJob), not a long-running service — a
    # daemon delivery thread gets killed mid-flight the instant this process
    # exits, so wait for them here or the alerts would routinely never send.
    for thread in pending_deliveries:
        thread.join(timeout=settings.alert_webhook_timeout_s + 1)
    log.info("checked cameras, %d offline", offline_count)
    return offline_count


if __name__ == "__main__":
    check_offline_cameras()
