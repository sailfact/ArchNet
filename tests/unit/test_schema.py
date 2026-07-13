"""JSON Schema layer: structural validation of config documents."""

import pytest

from fwos_core.validate import load_yaml, schema_errors, validate_yaml_text


def test_example_config_passes(example_doc, schema):
    assert schema_errors(example_doc, schema) == []


def test_example_config_builds_model(example_text, schema):
    config, errors = validate_yaml_text(example_text, schema)
    assert errors == []
    assert config.hostname == "fwos"
    assert config.interfaces["wan"].device == "eth0"
    assert config.interfaces["lan"].ipv4.address == "10.10.10.1/24"
    assert [rule.name for rule in config.rules] == ["lan-to-firewall", "lan-to-wan"]
    assert config.dhcp_servers[0].range.start == "10.10.10.100"
    assert config.dns.domain == "lan"


def test_yaml_parse_error_reported():
    doc, errors = load_yaml("interfaces: [unclosed")
    assert doc is None
    assert errors[0].code == "yaml-parse"


def test_yaml_non_mapping_rejected():
    doc, errors = load_yaml("- just\n- a\n- list\n")
    assert doc is None
    assert errors[0].code == "yaml-not-mapping"


def _breaking_edits():
    """(test id, mutation, expected error path prefix) table."""

    def missing_version(doc):
        del doc["version"]

    def wrong_version(doc):
        doc["version"] = 2

    def unknown_top_key(doc):
        doc["extra"] = {}

    def missing_dns_domain(doc):
        del doc["dns"]["domain"]

    def bad_upstream(doc):
        doc["dns"]["upstream"] = "unbound"

    def bad_cidr(doc):
        doc["interfaces"]["lan"]["ipv4"]["address"] = "10.10.10.1"

    def static_without_address(doc):
        del doc["interfaces"]["lan"]["ipv4"]["address"]

    def dhcp_with_address(doc):
        doc["interfaces"]["wan"]["ipv4"]["address"] = "192.0.2.2/24"

    def bad_action(doc):
        doc["rules"][0]["action"] = "reject"

    def bad_dport(doc):
        doc["rules"][0].update(protocol="tcp", dport=70000)

    def bad_lease(doc):
        doc["dhcp"]["servers"][0]["lease_time"] = "12 hours"

    def empty_zone(doc):
        doc["zones"]["lan"]["interfaces"] = []

    def bad_user_role(doc):
        doc["users"] = [{"name": "ops", "role": "viewer"}]

    return [
        ("missing-version", missing_version, "/"),
        ("wrong-version", wrong_version, "/version"),
        ("unknown-top-key", unknown_top_key, "/"),
        ("missing-dns-domain", missing_dns_domain, "/dns"),
        ("bad-upstream", bad_upstream, "/dns/upstream"),
        ("bad-cidr", bad_cidr, "/interfaces/lan/ipv4/address"),
        ("static-without-address", static_without_address, "/interfaces/lan/ipv4"),
        ("dhcp-with-address", dhcp_with_address, "/interfaces/wan/ipv4"),
        ("bad-action", bad_action, "/rules/0/action"),
        ("bad-dport", bad_dport, "/rules/0/dport"),
        ("bad-lease", bad_lease, "/dhcp/servers/0/lease_time"),
        ("empty-zone", empty_zone, "/zones/lan/interfaces"),
        ("bad-user-role", bad_user_role, "/users/0/role"),
    ]


@pytest.mark.parametrize(
    "mutate,path_prefix",
    [(edit, prefix) for _, edit, prefix in _breaking_edits()],
    ids=[test_id for test_id, _, _ in _breaking_edits()],
)
def test_invalid_documents_rejected(example_doc, schema, mutate, path_prefix):
    mutate(example_doc)
    errors = schema_errors(example_doc, schema)
    assert errors, "expected schema validation to fail"
    assert any(error.path.startswith(path_prefix) for error in errors), (
        f"no error under {path_prefix}: {[error.path for error in errors]}"
    )
    assert all(error.code == "schema" for error in errors)
