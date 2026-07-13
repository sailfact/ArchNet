"""Render systemd-networkd .network units from the config model."""

from __future__ import annotations

from typing import Dict

from ..model import Config, Interface
from .header import GENERATED_HEADER

NETWORK_DIR = "etc/systemd/network"


def _upstream_zones(config: Config) -> frozenset:
    """Zones used as a masquerade output are upstream (WAN-like); their
    units sort first so filenames stay stable as interfaces are added."""
    return frozenset(entry.out_zone for entry in config.masquerade)


def _unit_body(interface: Interface) -> str:
    lines = ["[Match]", f"Name={interface.device}", "", "[Network]"]
    if interface.ipv4.mode == "dhcp":
        lines += ["DHCP=ipv4", "IPv6AcceptRA=no"]
    else:
        lines += [
            f"Address={interface.ipv4.address}",
            "IPv6AcceptRA=no",
            "ConfigureWithoutCarrier=yes",
        ]
    return GENERATED_HEADER + "\n".join(lines) + "\n"


def render_networkd(config: Config) -> Dict[str, str]:
    """Return {relative path: unit content}, one unit per interface.

    Upstream-zone interfaces number from 20, all others from 30; the
    default config therefore yields 20-wan.network and 30-lan.network.
    """
    upstream_zones = _upstream_zones(config)
    upstream_interfaces = frozenset(
        name
        for zone_name in upstream_zones
        for name in config.zones[zone_name].interfaces
    )

    units: Dict[str, str] = {}
    for base, names in (
        (20, sorted(name for name in config.interfaces if name in upstream_interfaces)),
        (30, sorted(name for name in config.interfaces if name not in upstream_interfaces)),
    ):
        for offset, name in enumerate(names):
            path = f"{NETWORK_DIR}/{base + offset}-{name}.network"
            units[path] = _unit_body(config.interfaces[name])
    return units
