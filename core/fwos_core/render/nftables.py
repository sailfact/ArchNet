"""Render the nftables ruleset from the config model.

The implicit base policy (default-deny input/forward, conntrack
housekeeping, loopback, DHCP client lease traffic for dhcp-mode
interfaces) is emitted structurally and cannot be disabled from the
config; user rules are appended in document order.
"""

from __future__ import annotations

import ipaddress
from typing import List

from ..model import Config, FIREWALL_ZONE, Rule
from .header import GENERATED_HEADER

NFTABLES_PATH = "etc/nftables.conf"


def _zone_define(config: Config, zone_name: str) -> str:
    devices = [
        config.interfaces[iface_name].device
        for iface_name in config.zones[zone_name].interfaces
    ]
    if len(devices) == 1:
        return f'define {zone_name}_if = "{devices[0]}"'
    joined = ", ".join(f'"{device}"' for device in devices)
    return f"define {zone_name}_if = {{ {joined} }}"


def _match(rule: Rule) -> str:
    parts: List[str] = []
    if rule.dport is not None:
        dport = str(rule.dport)
        parts.append(f"{rule.protocol} dport {dport}")
    elif rule.protocol is not None:
        parts.append(f"meta l4proto {rule.protocol}")
    parts.append(rule.action)
    parts.append(f'comment "{rule.name}"')
    return " ".join(parts)


def _masquerade_saddr(config: Config, from_zone: str) -> str:
    """Constrain masquerade to the source zone's static subnets when they
    are all known; a zone with any dhcp interface falls back to matching
    on the output interface alone."""
    networks = []
    for iface_name in config.zones[from_zone].interfaces:
        interface = config.interfaces[iface_name]
        if interface.ipv4.mode != "static":
            return ""
        networks.append(str(ipaddress.ip_interface(interface.ipv4.address).network))
    if len(networks) == 1:
        return f"ip saddr {networks[0]} "
    return "ip saddr { " + ", ".join(sorted(networks)) + " } "


def render_nftables(config: Config) -> str:
    lines: List[str] = ["#!/usr/bin/nft -f", GENERATED_HEADER.rstrip("\n"), ""]
    lines.append("flush ruleset")
    lines.append("")
    for zone_name in sorted(config.zones):
        lines.append(_zone_define(config, zone_name))
    lines.append("")

    input_rules: List[str] = [
        "ct state invalid drop",
        "ct state established,related accept",
        'iifname "lo" accept',
    ]
    forward_rules: List[str] = [
        "ct state invalid drop",
        "ct state established,related accept",
    ]
    for rule in config.rules:
        line = f"iifname ${rule.from_zone}_if "
        if rule.to_zone != FIREWALL_ZONE:
            line += f"oifname ${rule.to_zone}_if "
        line += _match(rule)
        (input_rules if rule.to_zone == FIREWALL_ZONE else forward_rules).append(line)

    # DHCP client lease traffic for dhcp-mode interfaces, after user rules
    # so the default config keeps its Phase 2 rule order.
    for zone_name in sorted(config.zones):
        for iface_name in config.zones[zone_name].interfaces:
            interface = config.interfaces[iface_name]
            if interface.ipv4.mode != "dhcp":
                continue
            if len(config.zones[zone_name].interfaces) == 1:
                match = f"iifname ${zone_name}_if"
            else:
                match = f'iifname "{interface.device}"'
            input_rules.append(
                f"{match} udp sport 67 udp dport 68 accept"
                ' comment "WAN DHCP client lease traffic"'
            )

    lines.append("table inet filter {")
    lines.append("    chain input {")
    lines.append("        type filter hook input priority filter; policy drop;")
    lines.extend(f"        {rule}" for rule in input_rules)
    lines.append("    }")
    lines.append("")
    lines.append("    chain forward {")
    lines.append("        type filter hook forward priority filter; policy drop;")
    lines.extend(f"        {rule}" for rule in forward_rules)
    lines.append("    }")
    lines.append("")
    lines.append("    chain output {")
    lines.append("        type filter hook output priority filter; policy accept;")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append("table ip nat {")
    lines.append("    chain postrouting {")
    lines.append("        type nat hook postrouting priority srcnat; policy accept;")
    for entry in config.masquerade:
        saddr = _masquerade_saddr(config, entry.from_zone)
        lines.append(f"        {saddr}oifname ${entry.out_zone}_if masquerade")
    lines.append("    }")
    lines.append("}")
    return "\n".join(lines) + "\n"
