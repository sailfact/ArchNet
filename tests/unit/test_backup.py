"""Backup creation, pruning, restoration, and corruption detection."""

import json
from pathlib import Path

import pytest

from fwos_core.apply import backup
from fwos_core.apply.paths import Paths
from fwos_core.model import Config
from fwos_core.render import render_all

from fakes import FakeExecutor

PATHS = Paths(root=Path("/"))


@pytest.fixture
def system(example_text, example_doc):
    executor = FakeExecutor(log=[])
    executor.fs[str(PATHS.config_path)] = example_text
    executor.fs[str(PATHS.committed_config_path)] = example_text
    files = render_all(Config.from_dict(example_doc))
    for relpath, content in files.items():
        executor.fs[str(PATHS.root / relpath)] = content
    executor.fs[str(PATHS.manifest_path)] = (
        json.dumps({"files": {rel: "unused" for rel in files}}) + "\n"
    )
    return executor, files


def test_create_backup_contents_and_manifest(system, example_text):
    executor, files = system
    backup_id = backup.create_backup(executor, PATHS, "20260713T120000Z")
    assert backup_id == "20260713T120000Z"
    base = f"{PATHS.backups_dir}/{backup_id}"
    assert executor.fs[f"{base}/config.yaml"] == example_text
    manifest = json.loads(executor.fs[f"{base}/manifest.json"])
    assert set(manifest["files"]) == set(files)
    for relpath in files:
        assert executor.fs[f"{base}/files/{relpath}"] == files[relpath]


def test_backup_ids_deduplicate(system):
    executor, _ = system
    first = backup.create_backup(executor, PATHS, "20260713T120000Z")
    second = backup.create_backup(executor, PATHS, "20260713T120000Z")
    assert first == "20260713T120000Z"
    assert second == "20260713T120000Z-1"


def test_prune_keeps_newest_ten(system):
    executor, _ = system
    for hour in range(12):
        backup.create_backup(executor, PATHS, f"20260713T{hour:02d}0000Z")
    remaining = backup.list_backups(executor, PATHS)
    assert len(remaining) == 10
    assert remaining[0] == "20260713T020000Z"
    assert remaining[-1] == "20260713T110000Z"


def test_restore_round_trip(system, example_text):
    executor, files = system
    backup_id = backup.create_backup(executor, PATHS, "20260713T120000Z")
    executor.fs["/etc/dnsmasq.conf"] = "# clobbered\n"
    executor.fs[str(PATHS.config_path)] = "version: 1\n"

    touched = backup.restore_backup(executor, PATHS, backup_id)
    assert "etc/dnsmasq.conf" in touched
    assert executor.fs["/etc/dnsmasq.conf"] == files["etc/dnsmasq.conf"]
    assert executor.fs[str(PATHS.config_path)] == example_text
    assert executor.fs[str(PATHS.committed_config_path)] == example_text
    manifest = json.loads(executor.fs[str(PATHS.manifest_path)])
    assert set(manifest["files"]) == set(files)


def test_restore_unknown_backup(system):
    executor, _ = system
    with pytest.raises(backup.BackupError, match="not found"):
        backup.restore_backup(executor, PATHS, "nope")


def test_restore_detects_corruption(system):
    executor, _ = system
    backup_id = backup.create_backup(executor, PATHS, "20260713T120000Z")
    key = f"{PATHS.backups_dir}/{backup_id}/files/etc/dnsmasq.conf"
    executor.fs[key] += "tampered\n"
    with pytest.raises(backup.BackupError, match="corrupt"):
        backup.restore_backup(executor, PATHS, backup_id)


def test_managed_files_falls_back_to_committed_config(system):
    executor, files = system
    executor.remove(PATHS.manifest_path)
    assert backup.managed_files(executor, PATHS) == sorted(files)


def test_managed_files_empty_without_any_state(example_text):
    executor = FakeExecutor(log=[])
    assert backup.managed_files(executor, PATHS) == []


def test_backup_without_any_config_fails():
    executor = FakeExecutor(log=[])
    with pytest.raises(backup.BackupError, match="no config"):
        backup.create_backup(executor, PATHS, "20260713T120000Z")
