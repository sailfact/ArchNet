"""Semantic layer: cross-reference checks the JSON Schema cannot express."""

import pytest

from fwos_core.validate import semantic_errors, validate_document


def codes(doc):
    return [error.code for error in semantic_errors(doc)]


def test_example_config_has_no_semantic_errors(example_doc):
    assert semantic_errors(example_doc) == []


def test_zone_references_unknown_interface(example_doc):
    example_doc["zones"]["lan"]["interfaces"] = ["dmz"]
    errors = semantic_errors(example_doc)
    assert "unknown-interface" in [error.code for error in errors]
    assert any(error.path == "/zones/lan/interfaces/0" for error in errors)


def test_interface_in_two_zones(example_doc):
    example_doc["zones"]["wan"]["interfaces"] = ["wan", "lan"]
    assert "interface-in-two-zones" in codes(example_doc)


def test_interface_without_zone(example_doc):
    example_doc["interfaces"]["opt"] = {
        "device": "eth2",
        "ipv4": {"mode": "static", "address": "192.168.2.1/24"},
    }
    assert "interface-without-zone" in codes(example_doc)


def test_reserved_zone_name(example_doc):
    example_doc["zones"]["firewall"] = {"interfaces": ["lan"]}
    assert "reserved-zone" in codes(example_doc)


def test_duplicate_device(example_doc):
    example_doc["interfaces"]["lan"]["device"] = "eth0"
    assert "duplicate-device" in codes(example_doc)


def test_rule_unknown_zones(example_doc):
    example_doc["rules"][1]["from"] = "dmz"
    example_doc["rules"][1]["to"] = "guest"
    result = codes(example_doc)
    assert result.count("unknown-zone") == 2


def test_rule_from_firewall_rejected(example_doc):
    example_doc["rules"][0]["from"] = "firewall"
    example_doc["rules"][0]["to"] = "lan"
    assert "unknown-zone" in codes(example_doc)


def test_rule_same_zone(example_doc):
    example_doc["rules"][1]["to"] = "lan"
    assert "same-zone" in codes(example_doc)


def test_duplicate_rule_names(example_doc):
    example_doc["rules"][1]["name"] = example_doc["rules"][0]["name"]
    assert "duplicate-rule" in codes(example_doc)


def test_dport_without_protocol(example_doc):
    example_doc["rules"][0]["dport"] = 22
    assert "dport-needs-protocol" in codes(example_doc)


def test_dport_with_icmp(example_doc):
    example_doc["rules"][0].update(protocol="icmp", dport=22)
    assert "dport-needs-protocol" in codes(example_doc)


def test_bad_port_range(example_doc):
    example_doc["rules"][0].update(protocol="tcp", dport="800-70")
    assert "bad-port-range" in codes(example_doc)


def test_nat_unknown_zones(example_doc):
    example_doc["nat"]["masquerade"][0] = {"from": "dmz", "out": "guest"}
    assert codes(example_doc).count("unknown-zone") == 2


def test_dhcp_unknown_interface(example_doc):
    example_doc["dhcp"]["servers"][0]["interface"] = "dmz"
    assert "unknown-interface" in codes(example_doc)


def test_dhcp_on_dhcp_interface(example_doc):
    example_doc["dhcp"]["servers"][0]["interface"] = "wan"
    assert "dhcp-on-dynamic-interface" in codes(example_doc)


def test_dhcp_range_not_ordered(example_doc):
    example_doc["dhcp"]["servers"][0]["range"] = {
        "start": "10.10.10.200",
        "end": "10.10.10.100",
    }
    assert "range-not-ordered" in codes(example_doc)


def test_dhcp_range_outside_subnet(example_doc):
    example_doc["dhcp"]["servers"][0]["range"] = {
        "start": "10.10.20.100",
        "end": "10.10.20.200",
    }
    assert "range-outside-subnet" in codes(example_doc)


def test_dhcp_range_contains_interface_address(example_doc):
    example_doc["dhcp"]["servers"][0]["range"] = {
        "start": "10.10.10.1",
        "end": "10.10.10.200",
    }
    assert "range-contains-interface" in codes(example_doc)


def test_static_address_is_network_address(example_doc):
    example_doc["interfaces"]["lan"]["ipv4"]["address"] = "10.10.10.0/24"
    assert "bad-address" in codes(example_doc)


def test_static_address_is_broadcast_address(example_doc):
    example_doc["interfaces"]["lan"]["ipv4"]["address"] = "10.10.10.255/24"
    assert "bad-address" in codes(example_doc)


def test_services_ssh_unknown_zone(example_doc):
    example_doc["services"]["ssh"]["zones"] = ["dmz"]
    assert "unknown-zone" in codes(example_doc)


def test_schema_errors_gate_semantic_checks(example_doc, schema):
    # A structurally broken doc must fail at the schema layer without the
    # semantic pass running (which could crash on missing keys).
    del example_doc["zones"]
    errors = validate_document(example_doc, schema)
    assert errors
    assert all(error.code == "schema" for error in errors)
