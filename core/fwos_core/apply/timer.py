"""Rollback timer: the R1 lockout guard.

Armed before any file is installed; unless ``fwctl confirm`` cancels it
within the window, it fires ``fwctl rollback --pending`` and the previous
state comes back. Implemented as a systemd-run transient timer so nothing
extra ships in the image; hidden behind a protocol so tests use a fake.
"""

from __future__ import annotations

from typing import Protocol

from .executor import SystemExecutor

FWCTL = "/usr/local/bin/fwctl"


class TimerError(Exception):
    pass


class RollbackTimer(Protocol):
    def arm(self, session_id: str, timeout_s: int) -> None: ...

    def is_armed(self, session_id: str) -> bool: ...

    def cancel(self, session_id: str) -> None: ...


def _unit(session_id: str) -> str:
    return f"project-rollback-{session_id}"


class SystemdRunTimer:
    def __init__(self, executor: SystemExecutor, fwctl: str = FWCTL):
        self._executor = executor
        self._fwctl = fwctl

    def arm(self, session_id: str, timeout_s: int) -> None:
        result = self._executor.run(
            [
                "systemd-run",
                f"--unit={_unit(session_id)}",
                f"--on-active={timeout_s}s",
                "--timer-property=AccuracySec=1s",
                self._fwctl,
                "rollback",
                "--pending",
            ]
        )
        if not result.ok:
            raise TimerError(
                f"failed to arm rollback timer: {result.stderr.strip()}"
            )

    def is_armed(self, session_id: str) -> bool:
        result = self._executor.run(
            ["systemctl", "is-active", "--quiet", f"{_unit(session_id)}.timer"]
        )
        return result.ok

    def cancel(self, session_id: str) -> None:
        # Stopping a transient timer destroys it; tolerate it being gone
        # (e.g. it already fired), but only cancel once per session.
        self._executor.run(["systemctl", "stop", f"{_unit(session_id)}.timer"])
