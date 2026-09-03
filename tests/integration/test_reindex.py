import uuid

import numpy as np

from black_ice_common.vectorstore import alias_target, ensure_collection, search_face, upsert_face


def test_reindex_migrates_points_and_swaps_alias_with_zero_downtime(match_client):
    """match_client wires vectorstore.client to a fresh in-memory Qdrant; reused
    here purely for that throwaway backend."""
    import scripts.reindex_faces as reindex_module

    ensure_collection()
    old_collection = alias_target("faces")
    assert old_collection == "faces_v1"

    vec = np.random.default_rng(0).normal(size=512).astype(np.float32)
    vec /= np.linalg.norm(vec)
    point_id = str(uuid.uuid4())
    upsert_face(point_id, vec, "identity-1", "Alice")

    new_collection = reindex_module.reindex(alias="faces", new_suffix="v2", m=32, ef_construct=200, shard_number=1)
    assert new_collection == "faces_v2"

    # the alias now resolves to the new collection...
    assert alias_target("faces") == "faces_v2"
    # ...old collection is untouched, not deleted automatically
    assert "faces_v1" in [c.name for c in reindex_module.vectorstore.client.get_collections().collections]

    # search via the alias transparently hits the new collection, same data
    hits = search_face(vec, limit=1)
    assert len(hits) == 1
    assert hits[0].id == point_id
    assert hits[0].payload["identity_id"] == "identity-1"

    # a second enrollment after the swap lands in the new collection and is found
    vec2 = np.random.default_rng(1).normal(size=512).astype(np.float32)
    vec2 /= np.linalg.norm(vec2)
    point_id2 = str(uuid.uuid4())
    upsert_face(point_id2, vec2, "identity-2", "Bob")
    hits2 = search_face(vec2, limit=1)
    assert hits2[0].id == point_id2
