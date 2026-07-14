"""Render dnsmasq DHCP+DNS configuration from the config model.

dnsmasq is the MVP backend; everything here derives from backend-neutral
model fields so an unbound/kea profile can replace this module without a
model change.
"""

from __future__ import annotations

import ipaddress
from typing import List

from ..model import Config
from .header import GENERATED_HEADER

DNSMASQ_PATH = "etc/dnsmasq.conf"

UPSTREAM_RESOLV_FILES = {
    "resolved": "/run/systemd/resolve/resolv.conf",
}


def _interface_ip(config: Config, iface_name: str) -> str:
    address = config.interfaces[iface_name].ipv4.address
    return str(ipaddress.ip_interface(address).ip)


def render_dnsmasq(config: Config) -> str:
    servers = sorted(config.dhcp_servers, key=lambda server: server.interface)
    tagged = len(servers) > 1  # scope options per interface once there are several

    lines: List[str] = []
    for server in servers:
        lines.append(f"interface={config.interfaces[server.interface].device}")
    lines += [
        "bind-dynamic",
        "domain-needed",
        "bogus-priv",
        f"resolv-file={UPSTREAM_RESOLV_FILES[config.dns.upstream]}",
        f"domain={config.dns.domain}",
        f"local=/{config.dns.domain}/",
    ]
    for server in servers:
        lines.append(
            f"address=/{config.hostname}.{config.dns.domain}/"
            f"{_interface_ip(config, server.interface)}"
        )
    for record in config.dns.local_records:
        lines.append(f"address=/{record.name}/{record.address}")
    for server in servers:
        ip = _interface_ip(config, server.interface)
        set_tag = f"set:{server.interface}," if tagged else ""
        use_tag = f"tag:{server.interface}," if tagged else ""
        lines.append(
            f"dhcp-range={set_tag}{server.range.start},{server.range.end},"
            f"{server.lease_time}"
        )
        lines.append(f"dhcp-option={use_tag}option:router,{ip}")
        lines.append(f"dhcp-option={use_tag}option:dns-server,{ip}")
    lines.append("dhcp-authoritative")
    return GENERATED_HEADER + "\n".join(lines) + "\n"
