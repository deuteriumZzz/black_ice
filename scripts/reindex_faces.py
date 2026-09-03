"""Zero-downtime HNSW re-index / re-shard (spec: "Шардирование индекса, re-index
без даунтайма"). Creates a new concrete collection with the requested HNSW/shard
params, copies every point from the alias's current target, then atomically
swaps the alias — readers and writers keep using the alias name throughout and
never see a moment where it points at nothing.

ponytail: does a single copy pass, so writes landing in the old collection during
the (typically short) copy window aren't in the new one at swap time. Fine for a
demo/low-write-volume gallery; a live high-write system needs either a second
delta-copy pass right before the swap, or a brief write-pause — noted, not built.

Usage:
    python scripts/reindex_faces.py --m 32 --ef-construct 200 --shards 2
"""
import argparse
import logging

from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    HnswConfigDiff,
    PointStruct,
    VectorParams,
)

import black_ice_common.vectorstore as vectorstore
from black_ice_common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("reindex_faces")


def reindex(alias: str, new_suffix: str, m: int, ef_construct: int, shard_number: int, batch_size: int = 256) -> str:
    old_collection = vectorstore.alias_target(alias)
    if old_collection is None:
        raise RuntimeError(f"alias '{alias}' does not exist yet — nothing to reindex, run ensure_collection() first")

    new_collection = f"{alias}_{new_suffix}"
    log.info("creating %s (m=%d, ef_construct=%d, shards=%d)", new_collection, m, ef_construct, shard_number)
    vectorstore.client.create_collection(
        collection_name=new_collection,
        vectors_config=VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
        hnsw_config=HnswConfigDiff(m=m, ef_construct=ef_construct),
        shard_number=shard_number,
    )

    copied = 0
    offset = None
    while True:
        points, offset = vectorstore.client.scroll(collection_name=old_collection, limit=batch_size, offset=offset, with_vectors=True, with_payload=True)
        if not points:
            break
        vectorstore.client.upsert(
            collection_name=new_collection,
            points=[PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points],
        )
        copied += len(points)
        if offset is None:
            break
    log.info("copied %d points from %s to %s", copied, old_collection, new_collection)

    vectorstore.client.update_collection_aliases(
        change_aliases_operations=[
            DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)),
            CreateAliasOperation(create_alias=CreateAlias(collection_name=new_collection, alias_name=alias)),
        ]
    )
    log.info("alias '%s' now points at %s (old collection %s left in place — delete it manually once you've verified the swap)", alias, new_collection, old_collection)
    return new_collection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", default=settings.collection_name)
    parser.add_argument("--suffix", default="v2", help="new concrete collection name = <alias>_<suffix>")
    parser.add_argument("--m", type=int, default=settings.hnsw_m)
    parser.add_argument("--ef-construct", type=int, default=settings.hnsw_ef_construct)
    parser.add_argument("--shards", type=int, default=settings.qdrant_shard_number)
    args = parser.parse_args()
    reindex(args.alias, args.suffix, args.m, args.ef_construct, args.shards)


if __name__ == "__main__":
    main()
