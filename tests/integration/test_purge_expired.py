import datetime
import uuid

import numpy as np

import black_ice_common.db as db_module
from black_ice_common.db import Identity
from black_ice_common.vectorstore import search_face, upsert_face


def test_purge_removes_only_expired_identities(match_client):
    """match_client fixture wires sqlite + in-memory Qdrant — reuse it here purely
    for the throwaway backends, not the HTTP API. SessionLocal is read off the
    module (not imported by name) because the fixture patches it after this test
    module is first collected."""
    import scripts.purge_expired as purge_module

    purge_module.SessionLocal = db_module.SessionLocal

    with db_module.SessionLocal() as session:
        expired = Identity(
            name="Old", consent_given=True,
            retention_expires_at=datetime.datetime.utcnow() - datetime.timedelta(days=1),
        )
        fresh = Identity(
            name="New", consent_given=True,
            retention_expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=30),
        )
        session.add_all([expired, fresh])
        session.commit()
        session.refresh(expired)
        session.refresh(fresh)

    vec = np.random.default_rng(0).normal(size=512).astype(np.float32)
    vec /= np.linalg.norm(vec)
    upsert_face(str(uuid.uuid4()), vec, expired.id, "Old")
    upsert_face(str(uuid.uuid4()), vec, fresh.id, "New")

    purged = purge_module.purge_expired()
    assert purged == 1

    with db_module.SessionLocal() as session:
        assert session.get(Identity, expired.id) is None
        assert session.get(Identity, fresh.id) is not None

    hits = search_face(vec, limit=10)
    remaining_identity_ids = {h.payload["identity_id"] for h in hits}
    assert expired.id not in remaining_identity_ids
    assert fresh.id in remaining_identity_ids
