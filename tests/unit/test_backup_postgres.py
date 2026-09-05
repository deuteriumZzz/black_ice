import subprocess

import pytest


def test_pg_dump_url_strips_psycopg2_dialect_suffix():
    from scripts.backup_postgres import pg_dump_url

    assert pg_dump_url("postgresql+psycopg2://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_pg_dump_url_leaves_plain_url_unchanged():
    from scripts.backup_postgres import pg_dump_url

    assert pg_dump_url("postgresql://u:p@host:5432/db") == "postgresql://u:p@host:5432/db"


def test_backup_postgres_raises_on_pg_dump_failure(monkeypatch, tmp_path):
    import scripts.backup_postgres as backup_module

    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="connection refused")

    monkeypatch.setattr(backup_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="connection refused"):
        backup_module.backup_postgres(str(tmp_path))


def test_backup_postgres_returns_dump_path_on_success(monkeypatch, tmp_path):
    import scripts.backup_postgres as backup_module

    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(backup_module.subprocess, "run", fake_run)

    out_path = backup_module.backup_postgres(str(tmp_path))
    assert out_path.startswith(str(tmp_path))
    assert out_path.endswith(".dump")


def test_restore_postgres_raises_on_pg_restore_failure(monkeypatch):
    import scripts.restore_postgres as restore_module

    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="no such file")

    monkeypatch.setattr(restore_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="no such file"):
        restore_module.restore_postgres("/nonexistent.dump")
