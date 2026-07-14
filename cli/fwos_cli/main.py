"""fwctl: validate, render, apply, confirm, rollback, status.

Argument parsing and formatting only; every behavior lives in fwos_core.
Exit codes: 0 ok, 1 operational failure, 2 usage, 3 validation failed,
4 rendered config rejected by the Test stage.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import List, Optional

from fwos_core.apply import machine
from fwos_core.apply.backup import BackupError
from fwos_core.apply.executor import RealExecutor, SystemExecutor
from fwos_core.apply.paths import Paths
from fwos_core.apply.timer import RollbackTimer, SystemdRunTimer, TimerError
from fwos_core.render import render_all
from fwos_core.schema import SchemaNotFoundError, load_schema
from fwos_core.validate import ConfigInvalid

from .output import emit

EXIT_OK = 0
EXIT_OPERATIONAL = 1
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_TEST = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fwctl",
        description="Manage fwOS declaratively from /etc/project/config.yaml.",
    )
    parser.add_argument(
        "--json", action="store_true", help="machine-readable output"
    )
    parser.add_argument(
        "--config", metavar="PATH", help="config file (default: /etc/project/config.yaml)"
    )
    parser.add_argument(
        "--schema", metavar="PATH", help="schema file (default: installed schema)"
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        default="/",
        help="filesystem root to operate on (testing; default /)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate", help="validate the config and exit")

    render = commands.add_parser(
        "render", help="render the config and show a diff against live files"
    )
    render.add_argument(
        "--dry-run",
        action="store_true",
        help="diff against live files without writing (the default behavior)",
    )
    render.add_argument(
        "--output",
        metavar="DIR",
        help="write rendered files under DIR instead of diffing (build use)",
    )

    apply_cmd = commands.add_parser(
        "apply", help="validate, render, test, back up, and apply the config"
    )
    apply_cmd.add_argument(
        "--timeout",
        type=int,
        default=machine.DEFAULT_TIMEOUT_S,
        metavar="SECONDS",
        help="rollback window before an unconfirmed apply reverts"
        f" (default {machine.DEFAULT_TIMEOUT_S})",
    )

    commands.add_parser("confirm", help="commit the pending apply")

    rollback = commands.add_parser(
        "rollback", help="restore a backup (latest committed one by default)"
    )
    group = rollback.add_mutually_exclusive_group()
    group.add_argument("--to", metavar="BACKUP_ID", help="backup to restore")
    group.add_argument(
        "--pending",
        action="store_true",
        help="roll back the pending unconfirmed apply (used by the timer)",
    )

    commands.add_parser("status", help="engine state summary")
    return parser


def _render_dry_run(executor: SystemExecutor, paths: Paths, config) -> tuple:
    files = render_all(config)
    diffs: List[str] = []
    states = {}
    for relpath in sorted(files):
        live_path = paths.root / relpath
        live = (
            executor.read_text(live_path).splitlines(keepends=True)
            if executor.exists(live_path)
            else []
        )
        rendered = files[relpath].splitlines(keepends=True)
        if live == rendered:
            states[relpath] = "unchanged"
            continue
        states[relpath] = "new" if not live else "changed"
        diffs.extend(
            difflib.unified_diff(
                live, rendered, fromfile=f"live/{relpath}", tofile=f"rendered/{relpath}"
            )
        )
    diff_text = "".join(diffs)
    data = {"files": states, "diff": diff_text}
    human = [line.rstrip("\n") for line in diffs] or ["no changes"]
    return data, human


def _render_output(executor: SystemExecutor, output_root: Path, config) -> tuple:
    files = render_all(config)
    for relpath, content in sorted(files.items()):
        executor.write_text(output_root / relpath, content)
    data = {"files": sorted(files), "output": str(output_root)}
    human = [f"wrote {output_root / relpath}" for relpath in sorted(files)]
    return data, human


def main(
    argv: Optional[List[str]] = None,
    executor: Optional[SystemExecutor] = None,
    timer: Optional[RollbackTimer] = None,
) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_OK

    executor = executor if executor is not None else RealExecutor()
    timer = timer if timer is not None else SystemdRunTimer(executor)
    paths = Paths(
        root=Path(args.root),
        config_override=Path(args.config) if args.config else None,
    )
    action = args.command

    try:
        schema = load_schema(args.schema)
        if action == "validate":
            machine.load_and_validate(executor, paths, schema)
            data, human = {"valid": True}, ["configuration valid"]
        elif action == "render":
            config = machine.load_and_validate(executor, paths, schema)
            if args.output:
                data, human = _render_output(executor, Path(args.output), config)
            else:
                data, human = _render_dry_run(executor, paths, config)
        elif action == "apply":
            result = machine.apply(
                executor, timer, paths, schema=schema, timeout_s=args.timeout
            )
            data = result.as_dict()
            human = [
                f"applied {len(result.files)} files"
                f" (session {result.session_id}, backup {result.backup_id})",
                f"run `fwctl confirm` before {result.deadline} or the change"
                " rolls back automatically",
            ]
        elif action == "confirm":
            data = dict(machine.confirm(executor, timer, paths))
            human = [f"committed session {data['session_id']}"]
        elif action == "rollback":
            data = dict(
                machine.rollback(
                    executor,
                    timer,
                    paths,
                    backup_id=args.to,
                    pending_only=args.pending,
                )
            )
            human = [f"rolled back to backup {data['restored']}"]
        else:  # status
            data = dict(machine.status(executor, paths, schema))
            human = [
                f"config: {data['config_path']}"
                f" ({'valid' if data['valid'] else 'INVALID'})",
                f"pending: {data['pending'] or 'none'}",
                f"backups: {len(data['backups'])}",
            ]
            if "last_event" in data:
                human.append(f"last event: {data['last_event']}")
    except ConfigInvalid as exc:
        emit(
            args.json,
            action,
            ok=False,
            errors=[error.as_dict() for error in exc.errors],
        )
        return EXIT_INVALID
    except machine.TestStageFailed as exc:
        emit(
            args.json,
            action,
            ok=False,
            errors=[{"code": "test-stage", "message": f"{exc}: {exc.detail}"}],
        )
        return EXIT_TEST
    except (
        machine.OperationalError,
        BackupError,
        TimerError,
        SchemaNotFoundError,
        OSError,
    ) as exc:
        emit(
            args.json,
            action,
            ok=False,
            errors=[{"code": "operational", "message": str(exc)}],
        )
        return EXIT_OPERATIONAL

    emit(args.json, action, ok=True, data=data, human_lines=human)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
