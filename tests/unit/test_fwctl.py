"""fwctl wiring: subcommands, exit codes, and the JSON envelope."""

import json
from pathlib import Path

import pytest

from fwos_core.apply.paths import Paths
from fwos_core.model import Config
from fwos_core.render import render_all
from fwos_cli.main import main

from fakes import FakeExecutor, FakeTimer

PATHS = Paths(root=Path("/"))
SCHEMA = str(Path(__file__).resolve().parents[2] / "config" / "schema.json")


@pytest.fixture
def system(example_text, example_doc):
    log = []
    executor = FakeExecutor(log)
    timer = FakeTimer(log)
    executor.fs[str(PATHS.config_path)] = example_text
    executor.fs[str(PATHS.committed_config_path)] = example_text
    for relpath, content in render_all(Config.from_dict(example_doc)).items():
        executor.fs[str(PATHS.root / relpath)] = content
    return executor, timer


def fwctl(executor, timer, *argv):
    return main(["--schema", SCHEMA, *argv], executor=executor, timer=timer)


def envelope(capsys):
    return json.loads(capsys.readouterr().out)


def test_validate_ok(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "validate") == 0
    payload = envelope(capsys)
    assert payload["ok"] is True
    assert payload["action"] == "validate"
    assert payload["data"] == {"valid": True}
    assert payload["errors"] == []


def test_grouped_config_validate_and_alias_share_behavior(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "config", "validate") == 0
    grouped = envelope(capsys)
    assert grouped["action"] == "config.validate"
    assert grouped["data"] == {"valid": True}
    assert fwctl(executor, timer, "--json", "validate") == 0
    alias = envelope(capsys)
    assert alias["action"] == "validate"
    assert alias["data"] == grouped["data"]


def test_validate_invalid_exits_3(system, capsys):
    executor, timer = system
    executor.fs[str(PATHS.config_path)] = "version: 1\n"
    assert fwctl(executor, timer, "--json", "validate") == 3
    payload = envelope(capsys)
    assert payload["ok"] is False
    assert payload["errors"]
    assert all({"code", "message", "path"} <= set(e) for e in payload["errors"])


def test_validate_human_errors_on_stderr(system, capsys):
    executor, timer = system
    executor.fs[str(PATHS.config_path)] = "version: 1\n"
    assert fwctl(executor, timer, "validate") == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error [schema]" in captured.err


def test_render_dry_run_reports_no_changes(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "render", "--dry-run") == 0
    payload = envelope(capsys)
    assert set(payload["data"]["files"].values()) == {"unchanged"}
    assert payload["data"]["diff"] == ""


def test_grouped_config_render(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "config", "render") == 0
    payload = envelope(capsys)
    assert payload["action"] == "config.render"
    assert payload["data"]["diff"] == ""


def test_render_dry_run_diffs_without_writing(system, capsys):
    executor, timer = system
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace("10.10.10.200", "10.10.10.150")
    live_before = executor.fs["/etc/dnsmasq.conf"]

    assert fwctl(executor, timer, "--json", "render") == 0
    payload = envelope(capsys)
    assert payload["data"]["files"]["etc/dnsmasq.conf"] == "changed"
    assert "-dhcp-range=10.10.10.100,10.10.10.200,12h" in payload["data"]["diff"]
    assert "+dhcp-range=10.10.10.100,10.10.10.150,12h" in payload["data"]["diff"]
    assert executor.fs["/etc/dnsmasq.conf"] == live_before  # untouched


def test_render_output_writes_tree(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "render", "--output", "/build/airootfs") == 0
    assert "/build/airootfs/etc/nftables.conf" in executor.fs
    assert "/build/airootfs/etc/systemd/network/20-wan.network" in executor.fs


def test_apply_then_confirm(system, capsys):
    executor, timer = system
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace("10.10.10.200", "10.10.10.150")

    assert fwctl(executor, timer, "--json", "apply", "--timeout", "60") == 0
    payload = envelope(capsys)
    assert payload["ok"] is True
    assert payload["data"]["timeout_s"] == 60
    assert payload["data"]["deadline"]
    assert executor.exists(PATHS.pending_path)
    assert "10.10.10.150" in executor.fs["/etc/dnsmasq.conf"]

    assert fwctl(executor, timer, "--json", "confirm") == 0
    payload = envelope(capsys)
    assert payload["data"]["session_id"]
    assert not executor.exists(PATHS.pending_path)


def test_apply_test_stage_failure_exits_4(system, capsys):
    executor, timer = system
    executor.failing_commands["dnsmasq"] = "bad directive"
    assert fwctl(executor, timer, "--json", "apply") == 4
    payload = envelope(capsys)
    assert payload["errors"][0]["code"] == "test-stage"
    assert "bad directive" in payload["errors"][0]["message"]


def test_confirm_without_pending_exits_1(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "confirm") == 1
    payload = envelope(capsys)
    assert payload["errors"][0]["code"] == "operational"


def test_rollback_pending_restores(system, capsys):
    executor, timer = system
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace("10.10.10.200", "10.10.10.150")
    assert fwctl(executor, timer, "apply") == 0
    capsys.readouterr()  # drain the human-mode apply output
    assert fwctl(executor, timer, "--json", "rollback", "--pending") == 0
    payload = envelope(capsys)
    assert payload["data"]["restored"]
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]
    assert "10.10.10.200" in executor.fs[key]


def test_status_json(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "--json", "status") == 0
    payload = envelope(capsys)
    assert payload["data"]["valid"] is True
    assert payload["data"]["pending"] is None
    assert payload["data"]["backups"] == []
    assert payload["data"]["backup_count"] == 0
    assert set(payload["data"]["services"]) == {
        "systemd-networkd", "systemd-resolved", "nftables", "dnsmasq", "sshd"
    }
    assert payload["data"]["health"]["healthy"] is False


def test_status_reports_healthy_and_degraded_services(system, capsys):
    executor, timer = system
    for service in (
        "systemd-networkd", "systemd-resolved", "nftables", "dnsmasq", "sshd"
    ):
        executor.command_results[f"systemctl is-active {service}"] = (
            0, "active\n", ""
        )
    for device, address in (("eth0", "192.0.2.10"), ("eth1", "10.10.10.1")):
        executor.command_results[f"ip -j address show dev {device}"] = (
            0,
            f'[{{"operstate":"UP","addr_info":[{{"family":"inet",'
            f'"local":"{address}","prefixlen":24}}]}}]',
            "",
        )
    assert fwctl(executor, timer, "--json", "status") == 0
    payload = envelope(capsys)
    assert payload["data"]["health"] == {
        "healthy": True, "interfaces": True, "services": True
    }

    executor.command_results["systemctl is-active dnsmasq"] = (
        3, "inactive\n", ""
    )
    assert fwctl(executor, timer, "--json", "status") == 0
    payload = envelope(capsys)
    assert payload["data"]["services"]["dnsmasq"] == "inactive"
    assert payload["data"]["health"]["healthy"] is False


def test_status_keeps_invalid_config_as_read_only_degraded_report(system, capsys):
    executor, timer = system
    executor.fs[str(PATHS.config_path)] = "version: 1\n"
    assert fwctl(executor, timer, "--json", "status") == 0
    payload = envelope(capsys)
    assert payload["ok"] is True
    assert payload["data"]["valid"] is False
    assert payload["data"]["errors"]
    assert payload["data"]["health"]["healthy"] is False


def test_interfaces_joins_config_and_live_state(system, capsys):
    executor, timer = system
    executor.command_results["ip -j address show dev eth0"] = (
        0,
        '[{"ifname":"eth0","operstate":"UP","addr_info":'
        '[{"family":"inet","local":"192.0.2.10","prefixlen":24}]}]',
        "",
    )
    executor.command_results["ip -j address show dev eth1"] = (
        0,
        '[{"ifname":"eth1","operstate":"UP","addr_info":'
        '[{"family":"inet","local":"10.10.10.1","prefixlen":24}]}]',
        "",
    )
    assert fwctl(executor, timer, "--json", "interfaces") == 0
    payload = envelope(capsys)
    assert payload["data"]["healthy"] is True
    rows = {row["name"]: row for row in payload["data"]["interfaces"]}
    assert rows["wan"]["zone"] == "wan"
    assert rows["wan"]["ipv4"] == {"mode": "dhcp", "address": None}
    assert rows["lan"]["live"]["addresses"] == ["10.10.10.1/24"]


def test_interfaces_reports_unknown_live_state_without_failing(system, capsys):
    executor, timer = system
    executor.failing_commands["ip"] = "device unavailable"
    assert fwctl(executor, timer, "--json", "interfaces") == 0
    payload = envelope(capsys)
    assert payload["ok"] is True
    assert payload["data"]["healthy"] is False
    assert all(row["live"]["operational_state"] == "unknown"
               for row in payload["data"]["interfaces"])
    assert all("warning" in row for row in payload["data"]["interfaces"])


def test_backup_list_show_and_restore_use_existing_rollback(system, capsys):
    executor, timer = system
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace("10.10.10.200", "10.10.10.150")
    assert fwctl(executor, timer, "--json", "apply") == 0
    applied = envelope(capsys)
    backup_id = applied["data"]["backup_id"]
    assert fwctl(executor, timer, "--json", "confirm") == 0
    envelope(capsys)

    assert fwctl(executor, timer, "--json", "backup", "list") == 0
    listed = envelope(capsys)
    assert listed["action"] == "backup.list"
    assert listed["data"]["count"] == 1
    assert listed["data"]["backups"][0]["integrity"]["valid"] is True

    assert fwctl(executor, timer, "--json", "backup", "show", backup_id) == 0
    shown = envelope(capsys)
    assert shown["action"] == "backup.show"
    assert shown["data"]["backup_id"] == backup_id

    assert fwctl(executor, timer, "--json", "backup", "restore", backup_id) == 0
    restored = envelope(capsys)
    assert restored["action"] == "backup.restore"
    assert restored["data"]["restored"] == backup_id
    assert "10.10.10.200" in executor.fs[key]
    assert "prerollback" in restored["data"]["prerollback"]


def test_backup_show_reports_checksum_failure_without_mutating(system, capsys):
    executor, timer = system
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace("10.10.10.200", "10.10.10.150")
    assert fwctl(executor, timer, "--json", "apply") == 0
    backup_id = envelope(capsys)["data"]["backup_id"]
    backed_up = f"{PATHS.backups_dir}/{backup_id}/files/etc/dnsmasq.conf"
    executor.fs[backed_up] += "# corrupt\n"

    assert fwctl(executor, timer, "--json", "backup", "show", backup_id) == 0
    payload = envelope(capsys)
    assert payload["data"]["integrity"]["valid"] is False
    assert payload["data"]["integrity"]["files"]["etc/dnsmasq.conf"] is False

    live_before = dict(executor.fs)
    assert fwctl(
        executor, timer, "--json", "backup", "restore", backup_id
    ) == 1
    payload = envelope(capsys)
    assert "corrupt" in payload["errors"][0]["message"]
    assert executor.fs == live_before


def test_backup_show_unknown_id_is_operational_error(system, capsys):
    executor, timer = system
    assert fwctl(
        executor, timer, "--json", "backup", "show", "../../etc/project"
    ) == 1
    payload = envelope(capsys)
    assert payload["errors"][0]["code"] == "operational"


def test_usage_error_exits_2(system, capsys):
    executor, timer = system
    assert fwctl(executor, timer, "explode") == 2


def test_missing_config_is_operational(capsys):
    log = []
    assert main(
        ["--schema", SCHEMA, "--json", "validate"],
        executor=FakeExecutor(log),
        timer=FakeTimer(log),
    ) == 1
    payload = envelope(capsys)
    assert payload["errors"][0]["code"] == "operational"
    assert "not found" in payload["errors"][0]["message"]
