"""Retention sweep (spec: "Data retention policy: авто-удаление эмбеддингов через
N дней"). Meant to run as a K8s CronJob (infra/k8s/black-ice/templates/
retention-cronjob.yaml) or a cron/systemd-timer in non-k8s deployments — not an
in-process scheduler thread inside the match API, which would tie retention
correctness to that pod's uptime."""
import datetime
import logging

from black_ice_common.db import Identity, SessionLocal
from black_ice_common.vectorstore import delete_identity_vectors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("purge_expired")


def purge_expired(now: datetime.datetime | None = None) -> int:
    now = now or datetime.datetime.utcnow()
    purged = 0
    with SessionLocal() as session:
        expired = session.query(Identity).filter(
            Identity.retention_expires_at.isnot(None), Identity.retention_expires_at < now
        ).all()
        for identity in expired:
            delete_identity_vectors(identity.id)
            session.delete(identity)
            purged += 1
        session.commit()
    log.info("purged %d expired identities", purged)
    return purged


if __name__ == "__main__":
    purge_expired()
