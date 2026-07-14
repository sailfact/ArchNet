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
