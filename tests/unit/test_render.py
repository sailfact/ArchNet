"""Renderers: golden output for the default config, determinism, variants."""

from pathlib import Path

import pytest

from fwos_core.model import Config
from fwos_core.render import (
    GENERATED_HEADER,
    render_all,
    render_dnsmasq,
    render_networkd,
    render_nftables,
)

GOLDEN = Path(__file__).parent / "golden" / "default"

EXPECTED_PATHS = {
    "etc/nftables.conf",
    "etc/dnsmasq.conf",
    "etc/hostname",
    "etc/systemd/network/20-wan.network",
    "etc/systemd/network/30-lan.network",
}

# /etc/hostname must stay byte-identical to what hostnamectl writes back,
# so it is the one rendered file without the generated banner.
UNBANNERED = {"etc/hostname"}


@pytest.fixture
def config(example_doc):
    return Config.from_dict(example_doc)


def variant(example_doc, **changes):
    example_doc.update(changes)
    return Config.from_dict(example_doc)


def test_render_all_matches_golden(config):
    files = render_all(config)
    assert set(files) == EXPECTED_PATHS
    for rel, content in files.items():
        assert content == (GOLDEN / rel).read_text(encoding="utf-8"), rel


def test_render_is_deterministic(config, example_doc):
    again = Config.from_dict(example_doc)
    assert render_all(config) == render_all(again)


def test_every_file_carries_generated_header(config):
    for rel, content in render_all(config).items():
        if rel in UNBANNERED:
            continue
        assert GENERATED_HEADER in content, rel


def test_hostname_rendered_as_bare_name(config):
    assert render_all(config)["etc/hostname"] == "fwos\n"


def test_networkd_dhcp_and_static_bodies(config):
    units = render_networkd(config)
    wan = units["etc/systemd/network/20-wan.network"]
    lan = units["etc/systemd/network/30-lan.network"]
    assert "Name=eth0" in wan and "DHCP=ipv4" in wan
    assert "Address=" not in wan
    assert "Name=eth1" in lan and "Address=10.10.10.1/24" in lan
    assert "ConfigureWithoutCarrier=yes" in lan
    assert "DHCP=" not in lan


def test_networkd_numbering_for_added_interface(example_doc):
    example_doc["interfaces"]["dmz"] = {
        "device": "eth2",
        "ipv4": {"mode": "static", "address": "10.10.20.1/24"},
    }
    example_doc["zones"]["dmz"] = {"interfaces": ["dmz"]}
    units = render_networkd(Config.from_dict(example_doc))
    # Existing units keep their names; the new downstream zone slots after lan.
    assert set(units) == {
        "etc/systemd/network/20-wan.network",
        "etc/systemd/network/30-dmz.network",
        "etc/systemd/network/31-lan.network",
    }


def test_nftables_rule_with_port_and_protocol(example_doc):
    example_doc["rules"].append(
        {
            "name": "wan-web",
            "from": "wan",
            "to": "firewall",
            "action": "accept",
            "protocol": "tcp",
            "dport": 443,
        }
    )
    output = render_nftables(Config.from_dict(example_doc))
    assert 'iifname $wan_if tcp dport 443 accept comment "wan-web"' in output


def test_nftables_drop_rule_lands_in_forward_chain(example_doc):
    example_doc["interfaces"]["dmz"] = {
        "device": "eth2",
        "ipv4": {"mode": "static", "address": "10.10.20.1/24"},
    }
    example_doc["zones"]["dmz"] = {"interfaces": ["dmz"]}
    example_doc["rules"].append(
        {"name": "dmz-no-lan", "from": "dmz", "to": "lan", "action": "drop"}
    )
    output = render_nftables(Config.from_dict(example_doc))
    assert 'iifname $dmz_if oifname $lan_if drop comment "dmz-no-lan"' in output


def test_nftables_base_policy_is_always_present(config):
    output = render_nftables(config)
    assert output.count("policy drop;") == 2
    assert "ct state established,related accept" in output
    assert 'iifname "lo" accept' in output
    assert "udp sport 67 udp dport 68 accept" in output


def test_nftables_masquerade_scoped_to_static_source_subnet(config):
    output = render_nftables(config)
    assert "ip saddr 10.10.10.0/24 oifname $wan_if masquerade" in output


def test_nftables_masquerade_unscoped_when_source_has_dhcp_interface(example_doc):
    # Swap direction so the masquerade source zone contains a dhcp interface.
    example_doc["nat"]["masquerade"] = [{"from": "wan", "out": "lan"}]
    example_doc["rules"] = []
    output = render_nftables(Config.from_dict(example_doc))
    assert "oifname $lan_if masquerade" in output
    assert "ip saddr" not in output


def test_dnsmasq_local_records_rendered(example_doc):
    example_doc["dns"]["local_records"] = [
        {"name": "nas.lan", "address": "10.10.10.5"}
    ]
    output = render_dnsmasq(Config.from_dict(example_doc))
    assert "address=/nas.lan/10.10.10.5" in output
    assert "address=/fwos.lan/10.10.10.1" in output


def test_dnsmasq_variant_range(example_doc):
    example_doc["dhcp"]["servers"][0]["range"]["end"] = "10.10.10.150"
    output = render_dnsmasq(Config.from_dict(example_doc))
    assert "dhcp-range=10.10.10.100,10.10.10.150,12h" in output


def test_dnsmasq_multiple_servers_use_tags(example_doc):
    example_doc["interfaces"]["dmz"] = {
        "device": "eth2",
        "ipv4": {"mode": "static", "address": "10.10.20.1/24"},
    }
    example_doc["zones"]["dmz"] = {"interfaces": ["dmz"]}
    example_doc["dhcp"]["servers"].append(
        {
            "interface": "dmz",
            "range": {"start": "10.10.20.100", "end": "10.10.20.200"},
            "lease_time": "12h",
        }
    )
    output = render_dnsmasq(Config.from_dict(example_doc))
    assert "dhcp-range=set:dmz,10.10.20.100,10.10.20.200,12h" in output
    assert "dhcp-option=tag:lan,option:router,10.10.10.1" in output
    assert "interface=eth1" in output and "interface=eth2" in output
