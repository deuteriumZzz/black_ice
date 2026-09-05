"""Postgres restore counterpart to backup_postgres.py. Wraps pg_restore with
`--clean --if-exists` so tables from the dump replace what's currently there
rather than erroring on conflicting primary keys — destructive by design, only
ever run this against a database you mean to overwrite.

Usage:
    python scripts/restore_postgres.py --file ./backups/postgres/black_ice-20260101-030000.dump
"""
import argparse
import logging
import subprocess

from black_ice_common.config import settings
from scripts.backup_postgres import pg_dump_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("restore_postgres")


def restore_postgres(file_path: str) -> None:
    result = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "-d", pg_dump_url(settings.database_url), file_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_restore failed: {result.stderr}")
    log.info("restored database from %s", file_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    restore_postgres(args.file)


if __name__ == "__main__":
    main()
