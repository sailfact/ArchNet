"""Read-only inspection of configured and live appliance state."""

from __future__ import annotations

import json
from typing import Dict, Mapping, Sequence

from .apply.executor import SystemExecutor
from .model import Config


SERVICES: Sequence[str] = (
    "systemd-networkd",
    "systemd-resolved",
    "nftables",
    "dnsmasq",
    "sshd",
)


def _zones_by_interface(config: Config) -> Dict[str, str]:
    return {
        interface: zone
        for zone, spec in config.zones.items()
        for interface in spec.interfaces
    }


def interfaces(executor: SystemExecutor, config: Config) -> Mapping:
    """Return desired configuration joined to best-effort live state."""
    zones = _zones_by_interface(config)
    rows = []
    for name, interface in sorted(config.interfaces.items()):
        result = executor.run(["ip", "-j", "address", "show", "dev", interface.device])
        live = {
            "present": False,
            "operational_state": "unknown",
            "addresses": [],
        }
        warning = None
        if result.ok:
            try:
                documents = json.loads(result.stdout or "[]")
                document = documents[0] if documents else None
                if document is not None:
                    live = {
                        "present": True,
                        "operational_state": str(
                            document.get("operstate", "unknown")
                        ).lower(),
                        "addresses": sorted(
                            f"{item['local']}/{item['prefixlen']}"
                            for item in document.get("addr_info", [])
                            if item.get("family") in ("inet", "inet6")
                            and "local" in item
                            and "prefixlen" in item
                        ),
                    }
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                warning = f"could not parse live interface state: {exc}"
        else:
            warning = (result.stderr or "live interface state unavailable").strip()

        row = {
            "name": name,
            "device": interface.device,
            "zone": zones[name],
            "ipv4": {
                "mode": interface.ipv4.mode,
                "address": interface.ipv4.address,
            },
            "live": live,
            "healthy": live["present"]
            and live["operational_state"] not in ("down", "unknown"),
        }
        if warning:
            row["warning"] = warning
        rows.append(row)
    return {
        "interfaces": rows,
        "healthy": bool(rows) and all(row["healthy"] for row in rows),
    }


def services(executor: SystemExecutor) -> Mapping:
    """Return service activity without treating inactive units as CLI errors."""
    states = {}
    for service in SERVICES:
        result = executor.run(["systemctl", "is-active", service])
        state = result.stdout.strip().splitlines()
        states[service] = state[0] if state else "unknown"
    return {
        "services": states,
        "healthy": all(state == "active" for state in states.values()),
    }
