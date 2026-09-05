import types

import pytest
import responses


class _FakeSnapshotDescription:
    def __init__(self, name):
        self.name = name


def test_backup_qdrant_raises_when_alias_missing(monkeypatch, tmp_path):
    import black_ice_common.vectorstore as vectorstore
    import scripts.backup_qdrant as backup_module

    monkeypatch.setattr(vectorstore, "alias_target", lambda alias: None)

    with pytest.raises(RuntimeError, match="does not exist"):
        backup_module.backup_qdrant("faces", str(tmp_path))


@responses.activate
def test_backup_qdrant_downloads_snapshot_to_disk(monkeypatch, tmp_path):
    import black_ice_common.config as config
    import black_ice_common.vectorstore as vectorstore
    import scripts.backup_qdrant as backup_module

    monkeypatch.setattr(config.settings, "qdrant_url", "http://qdrant.test:6333")
    monkeypatch.setattr(backup_module, "settings", config.settings)
    monkeypatch.setattr(vectorstore, "alias_target", lambda alias: "faces_v1")
    monkeypatch.setattr(
        vectorstore, "client", types.SimpleNamespace(create_snapshot=lambda collection_name: _FakeSnapshotDescription("snap-123"))
    )

    responses.get("http://qdrant.test:6333/collections/faces_v1/snapshots/snap-123", body=b"fake-snapshot-bytes", status=200)

    out_path = backup_module.backup_qdrant("faces", str(tmp_path))

    assert out_path.endswith("faces__faces_v1__snap-123")
    with open(out_path, "rb") as f:
        assert f.read() == b"fake-snapshot-bytes"


def test_backup_qdrant_raises_when_snapshot_creation_returns_none(monkeypatch, tmp_path):
    import black_ice_common.vectorstore as vectorstore
    import scripts.backup_qdrant as backup_module

    monkeypatch.setattr(vectorstore, "alias_target", lambda alias: "faces_v1")
    monkeypatch.setattr(vectorstore, "client", types.SimpleNamespace(create_snapshot=lambda collection_name: None))

    with pytest.raises(RuntimeError, match="did not return a snapshot"):
        backup_module.backup_qdrant("faces", str(tmp_path))


@responses.activate
def test_restore_qdrant_uploads_and_repoints_alias(monkeypatch, tmp_path):
    import black_ice_common.config as config
    import black_ice_common.vectorstore as vectorstore
    import scripts.restore_qdrant as restore_module

    monkeypatch.setattr(config.settings, "qdrant_url", "http://qdrant.test:6333")
    monkeypatch.setattr(restore_module, "settings", config.settings)
    monkeypatch.setattr(vectorstore, "alias_target", lambda alias: "faces_v1")

    calls = []
    monkeypatch.setattr(
        vectorstore, "client", types.SimpleNamespace(update_collection_aliases=lambda change_aliases_operations: calls.append(change_aliases_operations))
    )

    snapshot_file = tmp_path / "faces__faces_v1__snap-abcdef1234567890.snapshot"
    snapshot_file.write_bytes(b"fake-snapshot-bytes")

    responses.post("http://qdrant.test:6333/collections/faces_restored_abcdef1234567890/snapshots/upload", json={"result": True}, status=200)

    collection = restore_module.restore_qdrant(str(snapshot_file), "faces")

    assert collection == "faces_restored_abcdef1234567890"
    assert len(calls) == 1
    ops = calls[0]
    # a pre-existing alias must be deleted before the new one is created, else
    # Qdrant rejects creating an alias name that's already taken
    assert len(ops) == 2


@responses.activate
def test_restore_qdrant_skips_delete_when_no_existing_alias(monkeypatch, tmp_path):
    import black_ice_common.config as config
    import black_ice_common.vectorstore as vectorstore
    import scripts.restore_qdrant as restore_module

    monkeypatch.setattr(config.settings, "qdrant_url", "http://qdrant.test:6333")
    monkeypatch.setattr(restore_module, "settings", config.settings)
    monkeypatch.setattr(vectorstore, "alias_target", lambda alias: None)

    calls = []
    monkeypatch.setattr(
        vectorstore, "client", types.SimpleNamespace(update_collection_aliases=lambda change_aliases_operations: calls.append(change_aliases_operations))
    )

    snapshot_file = tmp_path / "faces__faces_v1__snap-abcdef1234567890.snapshot"
    snapshot_file.write_bytes(b"fake-snapshot-bytes")

    responses.post("http://qdrant.test:6333/collections/faces_restored_abcdef1234567890/snapshots/upload", json={"result": True}, status=200)

    restore_module.restore_qdrant(str(snapshot_file), "faces")

    assert len(calls[0]) == 1, "no alias existed yet — nothing to delete before creating the new one"
