"""Apply state machine driven end-to-end with fakes: happy path, every
failure leg, and the lockout/rollback safety ordering."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fwos_core.apply import machine
from fwos_core.apply.backup import BackupError
from fwos_core.apply.paths import Paths
from fwos_core.apply.timer import TimerError
from fwos_core.model import Config
from fwos_core.render import render_all
from fwos_core.validate import ConfigInvalid

from fakes import FakeExecutor, FakeTimer

PATHS = Paths(root=Path("/"))


class TickingClock:
    """Strictly increasing clock so ids from consecutive calls differ."""

    def __init__(self):
        self._now = datetime(2026, 7, 13, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self._now += timedelta(seconds=1)
        return self._now


@pytest.fixture
def system(example_text, example_doc):
    """A 'booted appliance': live config, committed copy, rendered files."""
    log = []
    executor = FakeExecutor(log)
    timer = FakeTimer(log)
    executor.fs[str(PATHS.config_path)] = example_text
    executor.fs[str(PATHS.committed_config_path)] = example_text
    for relpath, content in render_all(Config.from_dict(example_doc)).items():
        executor.fs[str(PATHS.root / relpath)] = content
    return executor, timer, log


def edit_config(executor, old="10.10.10.200", new="10.10.10.150"):
    key = str(PATHS.config_path)
    assert old in executor.fs[key]
    executor.fs[key] = executor.fs[key].replace(old, new)


def run_apply(executor, timer, clock=None, **kwargs):
    return machine.apply(
        executor, timer, PATHS, clock=clock or TickingClock(), **kwargs
    )


def test_happy_path_apply_confirm(system, example_text):
    executor, timer, log = system
    edit_config(executor)
    clock = TickingClock()

    result = run_apply(executor, timer, clock)
    assert [stage.stage for stage in result.stages] == [
        "validate", "render", "test", "backup", "arm-rollback", "apply",
    ]

    # Rendered output is live and the old content is in the backup.
    assert "10.10.10.150" in executor.fs["/etc/dnsmasq.conf"]
    backup_dnsmasq = (
        f"{PATHS.backups_dir}/{result.backup_id}/files/etc/dnsmasq.conf"
    )
    assert "10.10.10.200" in executor.fs[backup_dnsmasq]
    backup_config = f"{PATHS.backups_dir}/{result.backup_id}/config.yaml"
    assert executor.fs[backup_config] == example_text  # committed, not live
    assert executor.exists(PATHS.pending_path)
    assert timer.armed  # still pending

    machine.confirm(executor, timer, PATHS, clock=clock)
    assert not executor.exists(PATHS.pending_path)
    assert timer.cancel_events() == [("cancel", result.session_id)]
    assert not timer.armed
    # COMMIT: the committed baseline is now the new text.
    assert "10.10.10.150" in executor.fs[str(PATHS.committed_config_path)]
    assert "committed" in executor.fs[str(PATHS.history_path)]


def test_safety_ordering_backup_then_timer_then_install(system):
    executor, timer, log = system
    edit_config(executor)
    result = run_apply(executor, timer)

    def first_index(predicate):
        return next(i for i, event in enumerate(log) if predicate(event))

    backup_prefix = f"{PATHS.backups_dir}/{result.backup_id}/"
    backup_done = max(
        i for i, e in enumerate(log)
        if e[0] == "write" and e[1].startswith(backup_prefix)
    )
    pending_written = first_index(
        lambda e: e == ("write", str(PATHS.pending_path))
    )
    armed = first_index(lambda e: e[0] == "arm")
    first_install = first_index(
        lambda e: e[0] == "write"
        and e[1].startswith("/etc/")
        and not e[1].startswith("/etc/project")
    )
    reload_ran = first_index(lambda e: e == ("run", "nft -f /etc/nftables.conf"))

    assert backup_done < pending_written < armed < first_install < reload_ran


def test_validation_failure_touches_nothing(system):
    executor, timer, log = system
    edit_config(executor, "10.10.10.200", "10.10.99.200")  # outside subnet
    before = dict(executor.fs)
    with pytest.raises(ConfigInvalid):
        run_apply(executor, timer)
    assert executor.fs == before
    assert timer.armed == {}


def test_test_stage_failure_aborts_before_backup(system):
    executor, timer, log = system
    edit_config(executor)
    executor.failing_commands["nft"] = "syntax error"
    with pytest.raises(machine.TestStageFailed):
        run_apply(executor, timer)
    assert executor.listdir(PATHS.backups_dir) == []
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]  # untouched
    assert not executor.exists(PATHS.pending_path)
    assert timer.armed == {}


def test_timer_arm_failure_blocks_apply(system):
    executor, timer, log = system
    edit_config(executor)
    timer.fail_arm = True
    with pytest.raises(TimerError):
        run_apply(executor, timer)
    assert not executor.exists(PATHS.pending_path)
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]


def test_timer_not_active_blocks_apply(system):
    executor, timer, log = system
    edit_config(executor)
    timer.report_armed = False
    with pytest.raises(TimerError):
        run_apply(executor, timer)
    assert not executor.exists(PATHS.pending_path)
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]


def test_reload_failure_self_rolls_back(system):
    executor, timer, log = system
    edit_config(executor)
    executor.failing_commands["systemctl"] = "dnsmasq failed to restart"
    with pytest.raises(machine.OperationalError) as excinfo:
        run_apply(executor, timer)
    assert excinfo.value.rolled_back
    # Old state restored, nothing left pending, timer cancelled.
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]
    assert not executor.exists(PATHS.pending_path)
    assert not timer.armed
    assert "apply-failed" in executor.fs[str(PATHS.history_path)]


def test_unconfirmed_apply_rolls_back_when_timer_fires(system, example_text):
    executor, timer, log = system
    edit_config(executor)
    clock = TickingClock()
    result = run_apply(executor, timer, clock)
    assert "10.10.10.150" in executor.fs["/etc/dnsmasq.conf"]

    # The window elapses with no confirm: the transient unit runs
    # `fwctl rollback --pending`.
    outcome = machine.rollback(
        executor, timer, PATHS, clock=clock, pending_only=True
    )
    assert outcome["restored"] == result.backup_id
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]
    assert executor.fs[str(PATHS.config_path)] == example_text
    assert executor.fs[str(PATHS.committed_config_path)] == example_text
    assert not executor.exists(PATHS.pending_path)
    # Forensics: the discarded state was saved with the *live* config text.
    prerollback_config = (
        f"{PATHS.backups_dir}/{outcome['prerollback']}/config.yaml"
    )
    assert "10.10.10.150" in executor.fs[prerollback_config]


def test_second_apply_refused_while_pending(system):
    executor, timer, log = system
    edit_config(executor)
    run_apply(executor, timer)
    with pytest.raises(machine.OperationalError, match="already pending"):
        run_apply(executor, timer)


def test_confirm_without_pending_fails(system):
    executor, timer, log = system
    with pytest.raises(machine.OperationalError, match="nothing to confirm"):
        machine.confirm(executor, timer, PATHS)


def test_rollback_pending_without_pending_fails(system):
    executor, timer, log = system
    with pytest.raises(machine.OperationalError, match="nothing pending"):
        machine.rollback(executor, timer, PATHS, pending_only=True)


def test_manual_rollback_to_latest_backup(system):
    executor, timer, log = system
    clock = TickingClock()
    edit_config(executor)
    result = run_apply(executor, timer, clock)
    machine.confirm(executor, timer, PATHS, clock=clock)
    assert "10.10.10.150" in executor.fs["/etc/dnsmasq.conf"]

    outcome = machine.rollback(executor, timer, PATHS, clock=clock)
    assert outcome["restored"] == result.backup_id
    assert "10.10.10.200" in executor.fs["/etc/dnsmasq.conf"]
    assert "10.10.10.200" in executor.fs[str(PATHS.config_path)]


def test_manual_rollback_unknown_id(system):
    executor, timer, log = system
    with pytest.raises(machine.OperationalError):
        machine.rollback(executor, timer, PATHS)  # no backups at all
    edit_config(executor)
    run_apply(executor, timer)
    with pytest.raises(BackupError, match="not found"):
        machine.rollback(executor, timer, PATHS, backup_id="20990101T000000Z")


def test_rollback_removes_stale_managed_files(system):
    executor, timer, log = system
    clock = TickingClock()
    # New interface => new networkd unit and renamed lan unit.
    key = str(PATHS.config_path)
    executor.fs[key] = executor.fs[key].replace(
        "interfaces:\n  wan:",
        "interfaces:\n  dmz:\n    device: eth2\n    ipv4:\n"
        "      mode: static\n      address: 10.10.20.1/24\n  wan:",
    ).replace(
        "zones:\n  wan:", "zones:\n  dmz:\n    interfaces: [dmz]\n  wan:"
    )
    run_apply(executor, timer, clock)
    assert executor.exists("/etc/systemd/network/30-dmz.network")
    assert executor.exists("/etc/systemd/network/31-lan.network")
    # Old 30-lan removed as stale during apply.
    assert not executor.exists("/etc/systemd/network/30-lan.network")

    machine.rollback(executor, timer, PATHS, clock=clock, pending_only=True)
    assert executor.exists("/etc/systemd/network/30-lan.network")
    assert not executor.exists("/etc/systemd/network/30-dmz.network")
    assert not executor.exists("/etc/systemd/network/31-lan.network")


def test_status_reports_pending_and_validity(system):
    executor, timer, log = system
    report = machine.status(executor, PATHS)
    assert report["valid"] is True
    assert report["pending"] is None

    edit_config(executor)
    result = run_apply(executor, timer)
    report = machine.status(executor, PATHS)
    assert report["pending"]["session_id"] == result.session_id
    assert result.backup_id in report["backups"]
    assert "applied" in report["last_event"]

    executor.fs[str(PATHS.config_path)] = "version: 1\n"
    report = machine.status(executor, PATHS)
    assert report["valid"] is False
    assert report["errors"]
