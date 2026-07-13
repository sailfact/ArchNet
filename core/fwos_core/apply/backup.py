"""Pre-apply backups and their restoration.

A backup is a plain directory under /var/lib/project/backups/<id>/:
    config.yaml       last committed config (rollback restores it)
    files/<relpath>   every rendered file the engine managed at the time
    manifest.json     ids and sha256 checksums for the above
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

from .executor import SystemExecutor
from .paths import Paths

KEEP_BACKUPS = 10


class BackupError(Exception):
    pass


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def managed_files(executor: SystemExecutor, paths: Paths) -> List[str]:
    """Root-relative paths of the rendered files the engine manages now.

    The state manifest is written on every apply; before the first apply
    (fresh image) it is derived by rendering the committed config, which
    the ISO build stages alongside the rendered files it produced.
    """
    if executor.exists(paths.manifest_path):
        manifest = json.loads(executor.read_text(paths.manifest_path))
        return list(manifest["files"])
    if executor.exists(paths.committed_config_path):
        from ..render import render_all
        from ..schema import load_schema
        from ..validate import ConfigInvalid, validate_yaml_text

        text = executor.read_text(paths.committed_config_path)
        config, errors = validate_yaml_text(text, load_schema())
        if errors:
            raise ConfigInvalid(errors)
        return sorted(render_all(config))
    return []


def _unique_backup_id(executor: SystemExecutor, paths: Paths, base: str) -> str:
    existing = set(executor.listdir(paths.backups_dir))
    if base not in existing:
        return base
    suffix = 1
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def create_backup(
    executor: SystemExecutor,
    paths: Paths,
    backup_id: str,
    label: Optional[str] = None,
    use_live_config: bool = False,
) -> str:
    """Snapshot the config and all managed rendered files.

    The pre-apply backup pairs the rendered files with the *committed*
    config (the live one was already edited to the new desired state); a
    pre-rollback forensic backup passes ``use_live_config=True`` because
    the live text is what described the state being discarded.

    ``backup_id`` should be a UTC timestamp (lexicographic == chronological);
    a ``label`` such as "prerollback" is appended to the directory name.
    """
    if label:
        backup_id = f"{backup_id}-{label}"
    backup_id = _unique_backup_id(executor, paths, backup_id)
    backup_dir = paths.backups_dir / backup_id

    if not use_live_config and executor.exists(paths.committed_config_path):
        config_text = executor.read_text(paths.committed_config_path)
    elif executor.exists(paths.config_path):
        # Never applied before: the live config is the best available
        # description of the running rendered state.
        config_text = executor.read_text(paths.config_path)
    else:
        raise BackupError(f"no config found at {paths.config_path}")

    files: Dict[str, str] = {}
    for relpath in managed_files(executor, paths):
        source = paths.root / relpath
        if not executor.exists(source):
            continue  # never managed or already gone; nothing to preserve
        content = executor.read_text(source)
        executor.write_text(backup_dir / "files" / relpath, content)
        files[relpath] = _sha256(content)

    executor.write_text(backup_dir / "config.yaml", config_text)
    executor.write_text(
        backup_dir / "manifest.json",
        json.dumps(
            {
                "backup_id": backup_id,
                "config_sha256": _sha256(config_text),
                "files": files,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    prune_backups(executor, paths)
    return backup_id


def list_backups(executor: SystemExecutor, paths: Paths) -> List[str]:
    return sorted(executor.listdir(paths.backups_dir))


def prune_backups(
    executor: SystemExecutor, paths: Paths, keep: int = KEEP_BACKUPS
) -> None:
    backups = list_backups(executor, paths)
    for backup_id in backups[:-keep] if len(backups) > keep else []:
        executor.rmtree(paths.backups_dir / backup_id)


def restore_backup(
    executor: SystemExecutor, paths: Paths, backup_id: str
) -> List[str]:
    """Put the backed-up config and rendered files back; returns the
    root-relative paths that were written or removed."""
    backup_dir = paths.backups_dir / backup_id
    manifest_path = backup_dir / "manifest.json"
    if not executor.exists(manifest_path):
        raise BackupError(f"backup {backup_id!r} not found")
    manifest = json.loads(executor.read_text(manifest_path))

    touched: List[str] = []
    # Remove files the engine manages now but did not manage back then.
    backup_files = set(manifest["files"])
    for relpath in managed_files(executor, paths):
        if relpath not in backup_files:
            executor.remove(paths.root / relpath)
            touched.append(relpath)
    for relpath, checksum in sorted(manifest["files"].items()):
        content = executor.read_text(backup_dir / "files" / relpath)
        if _sha256(content) != checksum:
            raise BackupError(f"backup {backup_id!r} is corrupt: {relpath}")
        executor.write_text(paths.root / relpath, content)
        touched.append(relpath)

    config_text = executor.read_text(backup_dir / "config.yaml")
    executor.write_text(paths.config_path, config_text)
    executor.write_text(paths.committed_config_path, config_text)
    executor.write_text(
        paths.manifest_path,
        json.dumps({"files": manifest["files"]}, indent=2, sort_keys=True) + "\n",
    )
    return touched
