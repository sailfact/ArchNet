"""In-memory SystemExecutor and RollbackTimer for driving the full apply
state machine without systemd, nft, or dnsmasq.

Both fakes append to one shared event log so tests can assert cross-cutting
ordering (backup before apply, timer armed before the first install).
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from fwos_core.apply.executor import CommandResult
from fwos_core.apply.timer import TimerError

Event = Tuple[str, ...]


class FakeExecutor:
    def __init__(self, log: List[Event]):
        self.fs: Dict[str, str] = {}
        self.log = log
        # command name -> stderr; presence makes that command fail (rc 1)
        self.failing_commands: Dict[str, str] = {}
        # full command line -> (return code, stdout, stderr)
        self.command_results: Dict[str, Tuple[int, str, str]] = {}

    def run(self, argv: Sequence[str]) -> CommandResult:
        self.log.append(("run", " ".join(argv)))
        name = argv[0]
        command = " ".join(argv)
        if command in self.command_results:
            returncode, stdout, stderr = self.command_results[command]
            return CommandResult(
                argv=tuple(argv), returncode=returncode,
                stdout=stdout, stderr=stderr,
            )
        if name in self.failing_commands:
            return CommandResult(
                argv=tuple(argv),
                returncode=1,
                stderr=self.failing_commands[name],
            )
        return CommandResult(argv=tuple(argv), returncode=0)

    def read_text(self, path) -> str:
        return self.fs[str(path)]

    def write_text(self, path, content: str) -> None:
        self.log.append(("write", str(path)))
        self.fs[str(path)] = content

    def exists(self, path) -> bool:
        key = str(path)
        return key in self.fs or any(
            name.startswith(key + "/") for name in self.fs
        )

    def listdir(self, path) -> List[str]:
        prefix = str(path).rstrip("/") + "/"
        entries = {
            name[len(prefix):].split("/", 1)[0]
            for name in self.fs
            if name.startswith(prefix)
        }
        return sorted(entries)

    def remove(self, path) -> None:
        self.log.append(("remove", str(path)))
        self.fs.pop(str(path), None)

    def rmtree(self, path) -> None:
        prefix = str(path).rstrip("/") + "/"
        self.log.append(("rmtree", str(path)))
        for name in [n for n in self.fs if n.startswith(prefix) or n == str(path)]:
            del self.fs[name]


class FakeTimer:
    def __init__(self, log: List[Event]):
        self.log = log
        self.armed: Dict[str, int] = {}
        self.fail_arm = False
        self.report_armed = True

    def arm(self, session_id: str, timeout_s: int) -> None:
        self.log.append(("arm", session_id, str(timeout_s)))
        if self.fail_arm:
            raise TimerError("injected arm failure")
        self.armed[session_id] = timeout_s

    def is_armed(self, session_id: str) -> bool:
        return self.report_armed and session_id in self.armed

    def cancel(self, session_id: str) -> None:
        self.log.append(("cancel", session_id))
        self.armed.pop(session_id, None)

    def cancel_events(self) -> List[Event]:
        return [event for event in self.log if event[0] == "cancel"]
