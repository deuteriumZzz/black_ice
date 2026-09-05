"""Qdrant backup (STATUS.md's HA/DR gap). Snapshots the concrete collection
behind an alias (see vectorstore.alias_target) and downloads the snapshot file
to local disk — leaving it inside Qdrant's own snapshot directory is not a real
backup, since that directory lives on the exact same volume as the collection
it's a snapshot of; losing the volume loses both.

Usage:
    python scripts/backup_qdrant.py --alias faces --out-dir ./backups/qdrant
"""
import argparse
import logging
import os

import requests

import black_ice_common.vectorstore as vectorstore
from black_ice_common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backup_qdrant")


def backup_qdrant(alias: str, out_dir: str) -> str:
    collection = vectorstore.alias_target(alias)
    if collection is None:
        raise RuntimeError(f"alias '{alias}' does not exist — nothing to back up")

    description = vectorstore.client.create_snapshot(collection_name=collection)
    if description is None:
        raise RuntimeError("Qdrant did not return a snapshot description")

    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{alias}__{collection}__{description.name}")
    url = f"{settings.qdrant_url}/collections/{collection}/snapshots/{description.name}"
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    log.info("backed up collection %s (alias %s) to %s", collection, alias, out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", default=settings.collection_name)
    parser.add_argument("--out-dir", default="./backups/qdrant")
    args = parser.parse_args()
    backup_qdrant(args.alias, args.out_dir)


if __name__ == "__main__":
    main()
