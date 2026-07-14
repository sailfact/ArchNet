"""Validation gate for the config model.

Two layers, both mandatory before any render or apply:
1. JSON Schema (structure, types, enums) against config/schema.json.
2. Semantic checks (cross-references and network arithmetic) that a
   document schema cannot express.

Every failure is reported as a structured ``ValidationError`` so the CLI,
and later the API, can surface machine-readable locations.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import List, Mapping, Optional, Tuple

import jsonschema
import yaml

from .model import FIREWALL_ZONE, Config


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str
    path: str  # JSON-pointer-ish location, e.g. "/dhcp/servers/0/range"

    def as_dict(self) -> Mapping[str, str]:
        return {"code": self.code, "message": self.message, "path": self.path}


class ConfigInvalid(Exception):
    """Raised by strict helpers when a document fails validation."""

    def __init__(self, errors: List[ValidationError]):
        super().__init__(f"{len(errors)} validation error(s)")
        self.errors = errors


def _pointer(parts) -> str:
    return "/" + "/".join(str(part) for part in parts) if parts else "/"


def load_yaml(text: str) -> Tuple[Optional[Mapping], List[ValidationError]]:
    """Parse YAML source; returns (document, errors)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [ValidationError("yaml-parse", str(exc), "/")]
    if not isinstance(doc, dict):
        return None, [
            ValidationError("yaml-not-mapping", "top level must be a mapping", "/")
        ]
    return doc, []


def schema_errors(doc: Mapping, schema: Mapping) -> List[ValidationError]:
    validator = jsonschema.Draft202012Validator(schema)
    return [
        ValidationError(
            "schema",
            error.message,
            _pointer(error.absolute_path),
        )
        for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def semantic_errors(doc: Mapping) -> List[ValidationError]:
    """Cross-reference checks; assumes the document already passed the schema."""
    errors: List[ValidationError] = []

    def err(code: str, message: str, path: str) -> None:
        errors.append(ValidationError(code, message, path))

    interfaces = doc["interfaces"]
    zones = doc["zones"]

    # Interface networks, parsed once for range checks below.
    networks = {}
    for name, spec in interfaces.items():
        if spec["ipv4"]["mode"] != "static":
            continue
        path = f"/interfaces/{name}/ipv4/address"
        try:
            iface = ipaddress.ip_interface(spec["ipv4"]["address"])
        except ValueError as exc:
            err("bad-address", str(exc), path)
            continue
        network = iface.network
        if network.prefixlen < 31 and iface.ip in (
            network.network_address,
            network.broadcast_address,
        ):
            err(
                "bad-address",
                f"{iface.ip} is the network or broadcast address of {network}",
                path,
            )
            continue
        networks[name] = iface

    # Duplicate devices across interfaces.
    seen_devices = {}
    for name, spec in interfaces.items():
        device = spec["device"]
        if device in seen_devices:
            err(
                "duplicate-device",
                f"device {device} already used by interface {seen_devices[device]}",
                f"/interfaces/{name}/device",
            )
        else:
            seen_devices[device] = name

    # Zones: reserved name, interface refs, exactly-one-zone membership.
    membership = {}
    for zone_name, spec in zones.items():
        if zone_name == FIREWALL_ZONE:
            err(
                "reserved-zone",
                f"zone name {FIREWALL_ZONE!r} is reserved for the appliance itself",
                f"/zones/{zone_name}",
            )
        for index, iface_name in enumerate(spec["interfaces"]):
            path = f"/zones/{zone_name}/interfaces/{index}"
            if iface_name not in interfaces:
                err("unknown-interface", f"unknown interface {iface_name!r}", path)
            elif iface_name in membership:
                err(
                    "interface-in-two-zones",
                    f"interface {iface_name!r} already in zone {membership[iface_name]!r}",
                    path,
                )
            else:
                membership[iface_name] = zone_name
    for iface_name in interfaces:
        if iface_name not in membership:
            err(
                "interface-without-zone",
                f"interface {iface_name!r} is not assigned to any zone",
                f"/interfaces/{iface_name}",
            )

    # Rules: zone refs, direction, protocol/dport pairing, unique names.
    seen_rules = set()
    for index, rule in enumerate(doc["rules"]):
        path = f"/rules/{index}"
        if rule["name"] in seen_rules:
            err("duplicate-rule", f"duplicate rule name {rule['name']!r}", f"{path}/name")
        seen_rules.add(rule["name"])
        if rule["from"] == FIREWALL_ZONE or rule["from"] not in zones:
            err("unknown-zone", f"unknown source zone {rule['from']!r}", f"{path}/from")
        if rule["to"] != FIREWALL_ZONE and rule["to"] not in zones:
            err("unknown-zone", f"unknown destination zone {rule['to']!r}", f"{path}/to")
        if rule["from"] == rule["to"]:
            err("same-zone", "rule source and destination zones are equal", path)
        if "dport" in rule and rule.get("protocol") not in ("tcp", "udp"):
            err(
                "dport-needs-protocol",
                "dport requires protocol tcp or udp",
                f"{path}/dport",
            )
        dport = rule.get("dport")
        if isinstance(dport, str):
            start, end = (int(part) for part in dport.split("-"))
            if not 1 <= start <= end <= 65535:
                err("bad-port-range", f"invalid port range {dport!r}", f"{path}/dport")

    # NAT masquerade zone references.
    for index, entry in enumerate(doc["nat"]["masquerade"]):
        path = f"/nat/masquerade/{index}"
        if entry["from"] not in zones:
            err("unknown-zone", f"unknown source zone {entry['from']!r}", f"{path}/from")
        if entry["out"] not in zones:
            err("unknown-zone", f"unknown output zone {entry['out']!r}", f"{path}/out")

    # DHCP servers: static interface, ordered range inside the subnet,
    # range must not contain the interface address.
    for index, server in enumerate(doc["dhcp"]["servers"]):
        path = f"/dhcp/servers/{index}"
        iface_name = server["interface"]
        if iface_name not in interfaces:
            err(
                "unknown-interface",
                f"unknown interface {iface_name!r}",
                f"{path}/interface",
            )
            continue
        if interfaces[iface_name]["ipv4"]["mode"] != "static":
            err(
                "dhcp-on-dynamic-interface",
                f"DHCP server interface {iface_name!r} must have a static address",
                f"{path}/interface",
            )
            continue
        if iface_name not in networks:
            continue  # address itself already reported as invalid
        iface = networks[iface_name]
        start = ipaddress.ip_address(server["range"]["start"])
        end = ipaddress.ip_address(server["range"]["end"])
        if start > end:
            err(
                "range-not-ordered",
                f"range start {start} is after end {end}",
                f"{path}/range",
            )
            continue
        if start not in iface.network or end not in iface.network:
            err(
                "range-outside-subnet",
                f"range {start}-{end} is not inside {iface.network}",
                f"{path}/range",
            )
            continue
        if start <= iface.ip <= end:
            err(
                "range-contains-interface",
                f"range {start}-{end} contains the interface address {iface.ip}",
                f"{path}/range",
            )

    # DNS local records.
    for index, record in enumerate(doc["dns"]["local_records"]):
        try:
            ipaddress.ip_address(record["address"])
        except ValueError as exc:
            err("bad-address", str(exc), f"/dns/local_records/{index}/address")

    # Services placeholder: zone references must still be real.
    for index, zone_name in enumerate(doc["services"]["ssh"]["zones"]):
        if zone_name not in zones:
            err(
                "unknown-zone",
                f"unknown zone {zone_name!r}",
                f"/services/ssh/zones/{index}",
            )

    return errors


def validate_document(doc: Mapping, schema: Mapping) -> List[ValidationError]:
    """Full validation gate: schema first, semantics only on a clean pass."""
    errors = schema_errors(doc, schema)
    if errors:
        return errors
    return semantic_errors(doc)


def validate_yaml_text(
    text: str, schema: Mapping
) -> Tuple[Optional[Config], List[ValidationError]]:
    """Parse and validate YAML source; returns (Config, []) or (None, errors)."""
    doc, errors = load_yaml(text)
    if errors:
        return None, errors
    errors = validate_document(doc, schema)
    if errors:
        return None, errors
    return Config.from_dict(doc), []
