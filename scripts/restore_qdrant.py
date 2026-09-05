"""Qdrant restore counterpart to backup_qdrant.py. Uploads a local snapshot
file back into Qdrant into a freshly-named collection, then atomically repoints
the alias at it — same swap pattern as reindex_faces.py, so readers/writers
never see a half-restored collection.

Usage:
    python scripts/restore_qdrant.py --file ./backups/qdrant/faces__faces_v1__snapshot-xyz.snapshot --alias faces
"""
import argparse
import logging
import os

import requests
from qdrant_client.models import CreateAlias, CreateAliasOperation, DeleteAlias, DeleteAliasOperation

import black_ice_common.vectorstore as vectorstore
from black_ice_common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("restore_qdrant")


def restore_qdrant(file_path: str, alias: str, restore_collection: str | None = None) -> str:
    if restore_collection is None:
        stem = os.path.basename(file_path).rsplit(".", 1)[0]
        restore_collection = f"{alias}_restored_{stem[-16:]}"

    url = f"{settings.qdrant_url}/collections/{restore_collection}/snapshots/upload"
    with open(file_path, "rb") as f:
        resp = requests.post(url, files={"snapshot": (os.path.basename(file_path), f)}, timeout=300)
    resp.raise_for_status()
    log.info("recovered snapshot into collection %s", restore_collection)

    ops = []
    if vectorstore.alias_target(alias) is not None:
        ops.append(DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)))
    ops.append(CreateAliasOperation(create_alias=CreateAlias(collection_name=restore_collection, alias_name=alias)))
    vectorstore.client.update_collection_aliases(change_aliases_operations=ops)
    log.info("alias '%s' now points at restored collection %s", alias, restore_collection)
    return restore_collection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--alias", default=settings.collection_name)
    args = parser.parse_args()
    restore_qdrant(args.file, args.alias)


if __name__ == "__main__":
    main()
