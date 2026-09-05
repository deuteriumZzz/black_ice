"""Postgres backup (STATUS.md's HA/DR gap). Wraps pg_dump in custom format
(`-Fc`) — compressed, supports parallel/selective restore via pg_restore; the
standard format for a real backup, unlike a plain-SQL dump.

Needs the `postgresql-client` package in the image (added to
services/match/Dockerfile) — this script reuses match's image via the same
CronJob pattern as scripts/purge_expired.py etc.

Usage:
    python scripts/backup_postgres.py --out-dir ./backups/postgres
"""
import argparse
import datetime
import logging
import os
import subprocess

from black_ice_common.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("backup_postgres")


def pg_dump_url(database_url: str) -> str:
    """pg_dump wants a plain postgresql:// URL — SQLAlchemy's +psycopg2 dialect
    suffix isn't a real Postgres URL scheme and pg_dump rejects it."""
    return database_url.replace("postgresql+psycopg2://", "postgresql://", 1)


def backup_postgres(out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(out_dir, f"black_ice-{ts}.dump")

    result = subprocess.run(
        ["pg_dump", "-Fc", "-f", out_path, pg_dump_url(settings.database_url)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {result.stderr}")
    log.info("backed up database to %s", out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="./backups/postgres")
    args = parser.parse_args()
    backup_postgres(args.out_dir)


if __name__ == "__main__":
    main()
