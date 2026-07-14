#!/usr/bin/env bash
set -euo pipefail
trap '' PIPE

# Boots a single firewall VM and exercises the Phase 4 management CLI end
# to end over serial:
#   - fwctl validate / status --json, and rendered files matching the ISO
#   - the R1 lockout drill: an unconfirmed apply is reverted by the
#     rollback timer, restoring config and services
#   - a confirmed apply that commits, with default-deny still intact
#   - a manual rollback to the pre-apply backup

fail() {
    printf 'qemu-config-lab: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 1 ]] || fail 'usage: qemu-config-lab.sh <iso-path>'
iso="$1"
[[ -f "$iso" ]] || fail "missing ISO: $iso"

qemu_bin="${QEMU_BIN:-qemu-system-x86_64}"
boot_timeout="${BOOT_TIMEOUT:-120}"
output_dir="${OUTPUT_DIR:-$(dirname "$iso")/test-logs}"
port_base="${LAB_PORT_BASE:-42700}"
[[ "$boot_timeout" =~ ^[1-9][0-9]*$ ]] || fail 'BOOT_TIMEOUT must be a positive integer'
[[ "$port_base" =~ ^[1-9][0-9]*$ ]] || fail 'LAB_PORT_BASE must be a positive integer'

if [[ "$qemu_bin" == */* ]]; then
    [[ -x "$qemu_bin" ]] || fail "QEMU is not executable: $qemu_bin"
else
    command -v "$qemu_bin" >/dev/null || fail "missing QEMU command: $qemu_bin"
fi

fw_serial_port=$((port_base))

mkdir -p "$output_dir"
fw_log="$output_dir/qemu-config-firewall.log"
: >"$fw_log"
fw_pid=''

cleanup() {
    if [[ -n "$fw_pid" ]] && kill -0 "$fw_pid" 2>/dev/null; then
        kill "$fw_pid" 2>/dev/null || true
        wait "$fw_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

accel='tcg'
[[ -r /dev/kvm && -w /dev/kvm ]] && accel='kvm'

# The guest's login shell decorates serial output with OSC/CSI escape
# sequences (shell-integration markers) glued onto the payload line.
csi_re=$'^\e\\[[0-9;?]*[[:alpha:]]'

open_serial() {
    local port=$1 pid=$2 attempt
    for ((attempt = 0; attempt < 100; attempt++)); do
        kill -0 "$pid" || return 1
        if exec {serial_fd}<>"/dev/tcp/127.0.0.1/$port"; then
            return 0
        fi
        sleep 0.2
    done
    return 1
} 2>/dev/null

serial_send() {
    printf '%s\n' "$2" >&"$1" 2>/dev/null || true
}

expect_line() {
    local fd=$1 pid=$2 timeout=$3 pattern=$4 log=$5
    local deadline=$((SECONDS + timeout)) line rc
    while ((SECONDS < deadline)); do
        rc=0
        read -t 1 -r -u "$fd" line || rc=$?
        if ((rc == 0)); then
            line=${line//$'\r'/}
            printf '%s\n' "$line" >>"$log"
            line=${line##*$'\a'}
            line=${line##*$'\e\\'}
            while [[ "$line" =~ $csi_re ]]; do
                line=${line#"${BASH_REMATCH[0]}"}
            done
            [[ "$line" =~ $pattern ]] && return 0
        elif ((rc <= 128)); then
            kill -0 "$pid" 2>/dev/null || fail "QEMU exited unexpectedly; see $log"
            sleep 0.2
        fi
    done
    return 1
}

wait_shell() {
    local fd=$1 pid=$2 log=$3 name=$4
    local deadline=$((SECONDS + boot_timeout)) attempt=0
    while ((SECONDS < deadline)); do
        attempt=$((attempt + 1))
        serial_send "$fd" "echo LAB-READY-$attempt"
        if expect_line "$fd" "$pid" 3 "^LAB-READY-$attempt\$" "$log"; then
            serial_send "$fd" 'stty -echo; dmesg -n 1; exec /usr/bin/bash --norc --noprofile -s'
            serial_send "$fd" 'echo LAB-SHELL-QUIET'
            expect_line "$fd" "$pid" 10 '^LAB-SHELL-QUIET$' "$log" ||
                fail "$name shell takeover failed; see $log"
            printf 'qemu-config-lab: %s shell is ready\n' "$name"
            return 0
        fi
    done
    fail "$name shell did not become ready within ${boot_timeout}s; see $log"
}

run_check() {
    local fd=$1 pid=$2 log=$3 timeout=$4 name=$5 cmd=$6
    serial_send "$fd" "{ $cmd ; } >/dev/null 2>&1 && echo LAB-PASS-$name || echo LAB-FAIL-$name"
    expect_line "$fd" "$pid" "$timeout" "^LAB-(PASS|FAIL)-$name\$" "$log" ||
        fail "check $name timed out after ${timeout}s; see $log"
    grep -qx "LAB-PASS-$name" "$log" || fail "check $name failed; see $log"
    printf 'qemu-config-lab: %s ok\n' "$name"
}

"$qemu_bin" \
    -machine q35 \
    -accel "$accel" \
    -m 1024 \
    -smp 2 \
    -boot order=d \
    -cdrom "$iso" \
    -display none \
    -monitor none \
    -no-reboot \
    -serial "tcp:127.0.0.1:$fw_serial_port,server=on,wait=on" \
    -netdev 'user,id=wan' \
    -device 'virtio-net-pci,netdev=wan,mac=52:54:00:0b:00:01,addr=0x4' \
    -netdev 'user,id=lan,restrict=on' \
    -device 'virtio-net-pci,netdev=lan,mac=52:54:00:0b:00:02,addr=0x5' \
    &
fw_pid=$!
open_serial "$fw_serial_port" "$fw_pid" || fail 'could not reach the firewall serial port'
fw_fd=$serial_fd

wait_shell "$fw_fd" "$fw_pid" "$fw_log" firewall

check() {
    run_check "$fw_fd" "$fw_pid" "$fw_log" "$@"
}

# Engine present and the shipped ISO matches the renderer exactly.
check 15 engine-staged \
    'test -f /usr/lib/fwos/schema.json && test -f /etc/project/config.yaml && test -f /var/lib/project/committed-config.yaml'
check 30 fwctl-validate 'fwctl validate'
check 30 fwctl-grouped-validate 'fwctl --json config validate | jq -e ".ok == true and .action == \"config.validate\""'
check 30 fwctl-grouped-render 'fwctl --json config render | jq -e ".ok == true and .data.diff == \"\""'
check 30 fwctl-interfaces \
    'fwctl --json interfaces | jq -e ".ok == true and (.data.interfaces | length) == 2 and (.data.interfaces | all(.live.present == true))"'
check 30 fwctl-status-json \
    'fwctl --json status | jq -e ".ok == true and .data.valid == true and .data.pending == null and .data.backup_count == 0 and (.data.services | length) == 5"'
check 30 render-matches-iso \
    'fwctl --json render | jq -e ".data.diff == \"\""'

# Lockout drill: apply with a short window and never confirm; the rollback
# timer must restore the previous DHCP range, config, and services.
check 15 lockout-edit-config \
    'sed -i "s/end: 10.10.10.200/end: 10.10.10.150/" /etc/project/config.yaml'
check 90 lockout-apply 'fwctl apply --timeout 20'
check 10 lockout-change-live 'grep -q "10.10.10.150" /etc/dnsmasq.conf'
check 10 lockout-pending-recorded 'test -f /var/lib/project/pending.json'
check 15 lockout-timer-armed \
    'systemctl list-timers --all | grep -q project-rollback'
check 120 lockout-rollback-fired \
    'for i in $(seq 90); do grep -q "10.10.10.200" /etc/dnsmasq.conf && break; sleep 1; done; grep -q "10.10.10.200" /etc/dnsmasq.conf'
check 30 lockout-pending-cleared \
    'for i in $(seq 20); do test ! -f /var/lib/project/pending.json && break; sleep 1; done; test ! -f /var/lib/project/pending.json'
check 10 lockout-config-restored 'grep -q "end: 10.10.10.200" /etc/project/config.yaml'
check 15 lockout-dnsmasq-active 'systemctl is-active --quiet dnsmasq'

# Happy path: apply and confirm inside the window; the change commits.
check 15 happy-edit-config \
    'sed -i "s/end: 10.10.10.200/end: 10.10.10.150/" /etc/project/config.yaml'
check 90 happy-apply 'fwctl apply --timeout 120'
check 10 happy-save-backup-id \
    'jq -r .backup_id /var/lib/project/pending.json > /run/phase4-backup-id && test -s /run/phase4-backup-id'
check 30 happy-confirm 'fwctl confirm'
check 10 happy-change-live 'grep -q "10.10.10.150" /etc/dnsmasq.conf'
check 10 happy-pending-cleared 'test ! -f /var/lib/project/pending.json'
check 10 happy-committed \
    'grep -q "end: 10.10.10.150" /var/lib/project/committed-config.yaml'
check 10 happy-default-deny-intact \
    'nft list chain inet filter input | grep -q "policy drop"'
check 10 happy-backups-exist '[ -n "$(ls /var/lib/project/backups)" ]'
check 30 happy-backup-list \
    'fwctl --json backup list | jq -e ".ok == true and .data.count >= 1 and (.data.backups | all(.integrity.valid == true))"'
check 30 happy-backup-show \
    'fwctl --json backup show "$(cat /run/phase4-backup-id)" | jq -e ".ok == true and .data.integrity.valid == true"'
check 15 happy-dnsmasq-active 'systemctl is-active --quiet dnsmasq'

# Explicit backup restoration returns to the pre-apply backup through the
# same rollback path and retains a forensic pre-rollback snapshot.
check 90 manual-rollback \
    'fwctl --json backup restore "$(cat /run/phase4-backup-id)" | jq -e ".ok == true and (.data.prerollback | contains(\"prerollback\"))"'
check 10 manual-rollback-live 'grep -q "10.10.10.200" /etc/dnsmasq.conf'
check 10 manual-rollback-config 'grep -q "end: 10.10.10.200" /etc/project/config.yaml'
check 15 manual-rollback-dnsmasq-active 'systemctl is-active --quiet dnsmasq'
check 30 final-status \
    'fwctl --json status | jq -e ".data.valid == true and .data.pending == null"'

printf 'qemu-config-lab: all checks passed\n'
