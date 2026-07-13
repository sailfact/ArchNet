"""Typed, immutable view of a validated configuration document.

Instances are only constructed from documents that already passed JSON
Schema and semantic validation; the constructors here do not re-validate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Union

# Zone name reserved for the appliance itself (nftables input chain).
FIREWALL_ZONE = "firewall"


@dataclass(frozen=True)
class Ipv4:
    mode: str  # "dhcp" | "static"
    address: Optional[str] = None  # CIDR, required when mode == "static"


@dataclass(frozen=True)
class Interface:
    name: str
    device: str
    ipv4: Ipv4


@dataclass(frozen=True)
class Zone:
    name: str
    interfaces: Sequence[str]


@dataclass(frozen=True)
class Rule:
    name: str
    from_zone: str
    to_zone: str
    action: str  # "accept" | "drop"
    protocol: Optional[str] = None  # "tcp" | "udp" | "icmp"
    dport: Optional[Union[int, str]] = None  # port or "start-end"
    comment: Optional[str] = None


@dataclass(frozen=True)
class Masquerade:
    from_zone: str
    out_zone: str


@dataclass(frozen=True)
class DhcpRange:
    start: str
    end: str


@dataclass(frozen=True)
class DhcpServer:
    interface: str
    range: DhcpRange
    lease_time: str


@dataclass(frozen=True)
class LocalRecord:
    name: str
    address: str


@dataclass(frozen=True)
class Dns:
    domain: str
    upstream: str  # "resolved"
    local_records: Sequence[LocalRecord] = ()


@dataclass(frozen=True)
class User:
    name: str
    role: str
    ssh_keys: Sequence[str] = ()


@dataclass(frozen=True)
class SshService:
    enabled: bool
    zones: Sequence[str] = ()


@dataclass(frozen=True)
class Services:
    ssh: SshService


@dataclass(frozen=True)
class Config:
    version: int
    hostname: str
    interfaces: Mapping[str, Interface]
    zones: Mapping[str, Zone]
    rules: Sequence[Rule]
    masquerade: Sequence[Masquerade]
    dhcp_servers: Sequence[DhcpServer]
    dns: Dns
    users: Sequence[User] = ()
    services: Services = field(
        default_factory=lambda: Services(ssh=SshService(enabled=False))
    )

    @classmethod
    def from_dict(cls, doc: Mapping) -> "Config":
        interfaces = {
            name: Interface(
                name=name,
                device=spec["device"],
                ipv4=Ipv4(
                    mode=spec["ipv4"]["mode"],
                    address=spec["ipv4"].get("address"),
                ),
            )
            for name, spec in doc["interfaces"].items()
        }
        zones = {
            name: Zone(name=name, interfaces=tuple(spec["interfaces"]))
            for name, spec in doc["zones"].items()
        }
        rules = tuple(
            Rule(
                name=rule["name"],
                from_zone=rule["from"],
                to_zone=rule["to"],
                action=rule["action"],
                protocol=rule.get("protocol"),
                dport=rule.get("dport"),
                comment=rule.get("comment"),
            )
            for rule in doc["rules"]
        )
        masquerade = tuple(
            Masquerade(from_zone=entry["from"], out_zone=entry["out"])
            for entry in doc["nat"]["masquerade"]
        )
        dhcp_servers = tuple(
            DhcpServer(
                interface=server["interface"],
                range=DhcpRange(
                    start=server["range"]["start"], end=server["range"]["end"]
                ),
                lease_time=server["lease_time"],
            )
            for server in doc["dhcp"]["servers"]
        )
        dns = Dns(
            domain=doc["dns"]["domain"],
            upstream=doc["dns"]["upstream"],
            local_records=tuple(
                LocalRecord(name=record["name"], address=record["address"])
                for record in doc["dns"]["local_records"]
            ),
        )
        users = tuple(
            User(
                name=user["name"],
                role=user["role"],
                ssh_keys=tuple(user.get("ssh_keys", ())),
            )
            for user in doc["users"]
        )
        services = Services(
            ssh=SshService(
                enabled=doc["services"]["ssh"]["enabled"],
                zones=tuple(doc["services"]["ssh"]["zones"]),
            )
        )
        return cls(
            version=doc["version"],
            hostname=doc["system"]["hostname"],
            interfaces=interfaces,
            zones=zones,
            rules=rules,
            masquerade=masquerade,
            dhcp_servers=dhcp_servers,
            dns=dns,
            users=users,
            services=services,
        )
