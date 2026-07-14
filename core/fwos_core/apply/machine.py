"""The apply state machine: Validate -> Render -> Test -> Apply -> Confirm -> Commit.

Hard safety ordering inside the Apply stage, guarding against admin
lockout (risk R1):

1. an unconditional pre-apply backup is taken first,
2. the rollback state (pending.json) is written and the rollback timer is
   armed and verified active,
3. only then is any file installed or any service reloaded.

``fwctl confirm`` cancels the timer and commits; if it never arrives the
timer fires ``fwctl rollback --pending`` and the backup comes back.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Mapping, Optional, Sequence

from ..model import Config
from ..render import DNSMASQ_PATH, NFTABLES_PATH, render_all
from ..schema import load_schema
from ..validate import ConfigInvalid, validate_yaml_text
from . import backup as backup_mod
from .executor import SystemExecutor
from .paths import Paths
from .timer import RollbackTimer, TimerError

DEFAULT_TIMEOUT_S = 120

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TestStageFailed(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class OperationalError(Exception):
    def __init__(self, message: str, rolled_back: bool = False):
        super().__init__(message)
        self.rolled_back = rolled_back


@dataclass(frozen=True)
class StageResult:
    stage: str
    detail: str = ""


@dataclass
class ApplyResult:
    session_id: str
    backup_id: str
    deadline: str
    timeout_s: int
    files: Sequence[str]
    stages: List[StageResult] = field(default_factory=list)

    def as_dict(self) -> Mapping:
        return {
            "session_id": self.session_id,
            "backup_id": self.backup_id,
            "deadline": self.deadline,
            "timeout_s": self.timeout_s,
            "files": list(self.files),
            "stages": [
                {"stage": stage.stage, "detail": stage.detail}
                for stage in self.stages
            ],
        }


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _timestamp(clock: Clock) -> str:
    return clock().strftime("%Y%m%dT%H%M%SZ")


def load_and_validate(
    executor: SystemExecutor, paths: Paths, schema: Optional[Mapping] = None
) -> Config:
    if not executor.exists(paths.config_path):
        raise OperationalError(f"config not found: {paths.config_path}")
    schema = schema if schema is not None else load_schema()
    config, errors = validate_yaml_text(
        executor.read_text(paths.config_path), schema
    )
    if errors:
        raise ConfigInvalid(errors)
    return config


def _reload_commands(
    paths: Paths,
    devices: Optional[Sequence[str]] = None,
    hostname: Optional[str] = None,
) -> List[List[str]]:
    commands = [
        ["nft", "-f", str(paths.root / NFTABLES_PATH)],
        ["networkctl", "reload"],
    ]
    # `networkctl reload` only re-reads unit files; the live links must be
    # reconfigured or an address change would not take effect until reboot,
    # silently defeating the confirm window.
    if devices:
        commands.append(["networkctl", "reconfigure", *devices])
    if hostname:
        commands.append(["hostnamectl", "set-hostname", hostname])
    commands.append(["systemctl", "restart", "dnsmasq"])
    return commands


def _reload_services(
    executor: SystemExecutor,
    paths: Paths,
    devices: Optional[Sequence[str]] = None,
    hostname: Optional[str] = None,
) -> List[str]:
    """Run the reload sequence; returns failure descriptions (empty == ok)."""
    failures = []
    for argv in _reload_commands(paths, devices, hostname):
        result = executor.run(argv)
        if not result.ok:
            failures.append(f"{' '.join(argv)}: {result.stderr.strip()}")
    return failures


def _devices(config: Config) -> List[str]:
    return sorted(
        interface.device for interface in config.interfaces.values()
    )


def _committed_context(
    executor: SystemExecutor, paths: Paths
) -> tuple:
    """(devices, hostname) from the committed config, for reloads after a
    restore; falls back to (None, None) so a rollback still reloads the
    base services even if the committed copy cannot be read."""
    try:
        schema = load_schema()
        config, errors = validate_yaml_text(
            executor.read_text(paths.committed_config_path), schema
        )
    except Exception:
        return None, None
    if errors or config is None:
        return None, None
    return _devices(config), config.hostname


def _read_pending(executor: SystemExecutor, paths: Paths) -> Optional[Mapping]:
    if not executor.exists(paths.pending_path):
        return None
    return json.loads(executor.read_text(paths.pending_path))


def _clear_pending(
    executor: SystemExecutor, timer: RollbackTimer, paths: Paths
) -> None:
    pending = _read_pending(executor, paths)
    if pending is not None:
        timer.cancel(pending["session_id"])
        executor.remove(paths.pending_path)


def _append_history(
    executor: SystemExecutor, paths: Paths, clock: Clock, line: str
) -> None:
    existing = (
        executor.read_text(paths.history_path)
        if executor.exists(paths.history_path)
        else ""
    )
    stamp = clock().strftime("%Y-%m-%dT%H:%M:%SZ")
    executor.write_text(paths.history_path, f"{existing}{stamp} {line}\n")


def apply(
    executor: SystemExecutor,
    timer: RollbackTimer,
    paths: Paths = Paths(),
    schema: Optional[Mapping] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    clock: Clock = _utcnow,
    session_id: Optional[str] = None,
) -> ApplyResult:
    if _read_pending(executor, paths) is not None:
        raise OperationalError(
            "an apply is already pending; run `fwctl confirm` or"
            " `fwctl rollback --pending` first"
        )
    session_id = session_id or _timestamp(clock)
    stages: List[StageResult] = []

    # VALIDATE
    config = load_and_validate(executor, paths, schema)
    stages.append(StageResult("validate"))

    # RENDER (to staging)
    files = render_all(config)
    staging = paths.staging_dir / session_id
    for relpath, content in sorted(files.items()):
        executor.write_text(staging / relpath, content)
    stages.append(StageResult("render", f"{len(files)} files"))

    # TEST
    for argv in (
        ["nft", "-c", "-f", str(staging / NFTABLES_PATH)],
        ["dnsmasq", "--test", f"--conf-file={staging / DNSMASQ_PATH}"],
    ):
        result = executor.run(argv)
        if not result.ok:
            raise TestStageFailed(
                f"{argv[0]} rejected the rendered config",
                detail=(result.stderr or result.stdout).strip(),
            )
    stages.append(StageResult("test"))

    # BACKUP (unconditional, before anything is touched)
    backup_id = backup_mod.create_backup(executor, paths, _timestamp(clock))
    stages.append(StageResult("backup", backup_id))

    # ARM ROLLBACK, then APPLY
    deadline = (clock() + timedelta(seconds=timeout_s)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    executor.write_text(
        paths.pending_path,
        json.dumps(
            {
                "session_id": session_id,
                "backup_id": backup_id,
                "timeout_s": timeout_s,
                "deadline": deadline,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    try:
        timer.arm(session_id, timeout_s)
        if not timer.is_armed(session_id):
            raise TimerError("rollback timer did not become active")
    except TimerError:
        executor.remove(paths.pending_path)
        raise
    stages.append(StageResult("arm-rollback", deadline))

    stale = set(backup_mod.managed_files(executor, paths)) - set(files)
    try:
        for relpath, content in sorted(files.items()):
            executor.write_text(paths.root / relpath, content)
        for relpath in sorted(stale):
            executor.remove(paths.root / relpath)
        executor.write_text(
            paths.manifest_path,
            json.dumps(
                {"files": {rel: _sha256(text) for rel, text in files.items()}},
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        failures = _reload_services(
            executor, paths, _devices(config), config.hostname
        )
        if failures:
            raise OperationalError("; ".join(failures))
    except Exception as exc:
        # Self-rollback: the admin may already be locked out.
        backup_mod.restore_backup(executor, paths, backup_id)
        _reload_services(executor, paths, *_committed_context(executor, paths))
        timer.cancel(session_id)
        executor.remove(paths.pending_path)
        _append_history(
            executor, paths, clock, f"apply-failed session={session_id}: {exc}"
        )
        raise OperationalError(
            f"apply failed and was rolled back: {exc}", rolled_back=True
        ) from exc
    finally:
        executor.rmtree(staging)

    stages.append(StageResult("apply", f"{len(files)} files installed"))
    _append_history(
        executor,
        paths,
        clock,
        f"applied session={session_id} backup={backup_id} deadline={deadline}",
    )
    return ApplyResult(
        session_id=session_id,
        backup_id=backup_id,
        deadline=deadline,
        timeout_s=timeout_s,
        files=sorted(files),
        stages=stages,
    )


def confirm(
    executor: SystemExecutor,
    timer: RollbackTimer,
    paths: Paths = Paths(),
    clock: Clock = _utcnow,
) -> Mapping:
    pending = _read_pending(executor, paths)
    if pending is None:
        raise OperationalError("nothing to confirm: no apply is pending")
    timer.cancel(pending["session_id"])
    executor.remove(paths.pending_path)
    # COMMIT: the live config becomes the committed baseline.
    executor.write_text(
        paths.committed_config_path, executor.read_text(paths.config_path)
    )
    _append_history(
        executor, paths, clock, f"committed session={pending['session_id']}"
    )
    return {"session_id": pending["session_id"], "backup_id": pending["backup_id"]}


def rollback(
    executor: SystemExecutor,
    timer: RollbackTimer,
    paths: Paths = Paths(),
    clock: Clock = _utcnow,
    backup_id: Optional[str] = None,
    pending_only: bool = False,
) -> Mapping:
    pending = _read_pending(executor, paths)
    if pending_only:
        if pending is None:
            raise OperationalError("nothing pending to roll back")
        backup_id = pending["backup_id"]
    elif backup_id is None:
        backups = [
            candidate
            for candidate in backup_mod.list_backups(executor, paths)
            if "prerollback" not in candidate
        ]
        if not backups:
            raise OperationalError("no backups available to roll back to")
        backup_id = backups[-1]

    if not executor.exists(paths.backups_dir / backup_id / "manifest.json"):
        raise backup_mod.BackupError(f"backup {backup_id!r} not found")

    # Preserve the state being discarded; the live config text describes it.
    # The restore target is exempt from pruning or it could be deleted here.
    prerollback_id = backup_mod.create_backup(
        executor,
        paths,
        _timestamp(clock),
        label="prerollback",
        use_live_config=True,
        preserve={backup_id},
    )
    backup_mod.restore_backup(executor, paths, backup_id)
    failures = _reload_services(executor, paths, *_committed_context(executor, paths))
    _clear_pending(executor, timer, paths)
    _append_history(
        executor,
        paths,
        clock,
        f"rolled-back to={backup_id} prerollback={prerollback_id}",
    )
    if failures:
        raise OperationalError(
            "rolled back, but service reload failed: " + "; ".join(failures)
        )
    return {"restored": backup_id, "prerollback": prerollback_id}


def status(
    executor: SystemExecutor,
    paths: Paths = Paths(),
    schema: Optional[Mapping] = None,
) -> Mapping:
    result: dict = {
        "config_path": str(paths.config_path),
        "valid": False,
        "errors": [],
        "pending": None,
        "backups": backup_mod.list_backups(executor, paths),
    }
    if executor.exists(paths.config_path):
        text = executor.read_text(paths.config_path)
        result["config_sha256"] = _sha256(text)
        try:
            load_and_validate(executor, paths, schema)
            result["valid"] = True
        except ConfigInvalid as exc:
            result["errors"] = [error.as_dict() for error in exc.errors]
    else:
        result["errors"] = [
            {"code": "missing", "message": "config file not found", "path": "/"}
        ]
    pending = _read_pending(executor, paths)
    if pending is not None:
        result["pending"] = dict(pending)
    if executor.exists(paths.history_path):
        lines = executor.read_text(paths.history_path).strip().splitlines()
        if lines:
            result["last_event"] = lines[-1]
    return result
