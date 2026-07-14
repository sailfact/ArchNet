"""System-effect boundary.

Every command execution and file write the apply machinery performs goes
through a ``SystemExecutor`` so the full state machine can run under test
with an in-memory fake, on a dev box with no systemd, nft, or dnsmasq.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Protocol, Sequence, Union

PathLike = Union[str, Path]


@dataclass(frozen=True)
class CommandResult:
    argv: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class SystemExecutor(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...

    def read_text(self, path: PathLike) -> str: ...

    def write_text(self, path: PathLike, content: str) -> None: ...

    def exists(self, path: PathLike) -> bool: ...

    def listdir(self, path: PathLike) -> List[str]: ...

    def remove(self, path: PathLike) -> None: ...

    def rmtree(self, path: PathLike) -> None: ...


class RealExecutor:
    """Executes for real: subprocess + atomic file writes."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(argv), capture_output=True, text=True, check=False
        )
        return CommandResult(
            argv=tuple(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def read_text(self, path: PathLike) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: PathLike, content: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}."
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise

    def exists(self, path: PathLike) -> bool:
        return Path(path).exists()

    def listdir(self, path: PathLike) -> List[str]:
        target = Path(path)
        if not target.is_dir():
            return []
        return sorted(entry.name for entry in target.iterdir())

    def remove(self, path: PathLike) -> None:
        Path(path).unlink(missing_ok=True)

    def rmtree(self, path: PathLike) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)
