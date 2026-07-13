"""Filesystem layout of the engine's runtime state.

Everything is expressed relative to an injectable root so tests and the
QEMU lab can run the whole machine against a scratch directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Paths:
    root: Path = Path("/")
    config_override: Optional[Path] = None

    @property
    def config_path(self) -> Path:
        if self.config_override is not None:
            return self.config_override
        return self.root / "etc/project/config.yaml"

    @property
    def state_dir(self) -> Path:
        return self.root / "var/lib/project"

    @property
    def backups_dir(self) -> Path:
        return self.state_dir / "backups"

    @property
    def pending_path(self) -> Path:
        return self.state_dir / "pending.json"

    @property
    def manifest_path(self) -> Path:
        """Manifest of the rendered files the engine currently manages."""
        return self.state_dir / "manifest.json"

    @property
    def committed_config_path(self) -> Path:
        """Copy of the last committed config; the pre-apply backup uses it
        because /etc/project/config.yaml is edited in place before apply."""
        return self.state_dir / "committed-config.yaml"

    @property
    def history_path(self) -> Path:
        return self.state_dir / "history.log"

    @property
    def staging_dir(self) -> Path:
        return self.root / "run/project/staging"
