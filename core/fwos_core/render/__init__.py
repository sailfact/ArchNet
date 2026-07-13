"""Renderers: pure functions from the validated config model to file text.

``render_all`` is the single entry point the apply machinery and the ISO
build use; its keys (paths relative to the filesystem root) are the
complete set of files the engine manages.
"""

from __future__ import annotations

from typing import Dict

from ..model import Config
from .dnsmasq import DNSMASQ_PATH, render_dnsmasq
from .header import GENERATED_HEADER
from .networkd import NETWORK_DIR, render_networkd
from .nftables import NFTABLES_PATH, render_nftables

__all__ = [
    "GENERATED_HEADER",
    "NETWORK_DIR",
    "NFTABLES_PATH",
    "DNSMASQ_PATH",
    "render_networkd",
    "render_nftables",
    "render_dnsmasq",
    "render_all",
]


def render_all(config: Config) -> Dict[str, str]:
    """Return {root-relative path: content} for every managed file."""
    files: Dict[str, str] = {
        NFTABLES_PATH: render_nftables(config),
        DNSMASQ_PATH: render_dnsmasq(config),
    }
    files.update(render_networkd(config))
    return files
