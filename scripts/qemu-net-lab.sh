#!/usr/bin/env bash
set -euo pipefail
trap '' PIPE

# Boots the standard Phase 2 topology and verifies it end to end:
#   host http server <- slirp WAN -> [fwos firewall] <- LAN stream socket -> [fwos LAN client]
# The client must get a dnsmasq lease, resolve DNS through the firewall, and
# reach the WAN through NAT; unsolicited WAN ingress must be dropped.

fail() {
    printf 'qemu-net-lab: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 1 ]] || fail 'usage: qemu-net-lab.sh <iso-path>'
iso="$1"
[[ -f "$iso" ]] || fail "missing ISO: $iso"

qemu_bin="${QEMU_BIN:-qemu-system-x86_64}"
boot_timeout="${BOOT_TIMEOUT:-120}"
output_dir="${OUTPUT_DIR:-$(dirname "$iso")/test-logs}"
port_base="${LAB_PORT_BASE:-42600}"
[[ "$boot_timeout" =~ ^[1-9][0-9]*$ ]] || fail 'BOOT_TIMEOUT must be a positive integer'
[[ "$port_base" =~ ^[1-9][0-9]*$ ]] || fail 'LAB_PORT_BASE must be a positive integer'

if [[ "$qemu_bin" == */* ]]; then
    [[ -x "$qemu_bin" ]] || fail "QEMU is not executable: $qemu_bin"
else
    command -v "$qemu_bin" >/dev/null || fail "missing QEMU command: $qemu_bin"
fi
command -v python3 >/dev/null || fail 'missing python3 (needed for the WAN-side HTTP target)'

fw_serial_port=$((port_base))
client_serial_port=$((port_base + 1))
lan_port=$((port_base + 2))
wan_probe_port=$((port_base + 3))
http_port=$((port_base + 4))

mkdir -p "$output_dir"
fw_log="$output_dir/qemu-net-firewall.log"
client_log="$output_dir/qemu-net-client.log"
: >"$fw_log"
: >"$client_log"
tmpdir="$(mktemp -d)"
fw_pid=''
client_pid=''
http_pid=''

cleanup() {
    local pid
    for pid in "$fw_pid" "$client_pid" "$http_pid"; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

accel='tcg'
[[ -r /dev/kvm && -w /dev/kvm ]] && accel='kvm'

common_args=(
    -machine q35
    -accel "$accel"
    -m 1024
    -smp 2
    -boot order=d
    -cdrom "$iso"
    -display none
    -monitor none
    -no-reboot
)

printf 'lab probe\n' >"$tmpdir/index.html"
python3 -m http.server --bind 127.0.0.1 --directory "$tmpdir" "$http_port" \
    >/dev/null 2>&1 &
http_pid=$!

# Connects to a QEMU serial TCP server and leaves the socket on $serial_fd.
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

# The guest's login shell decorates serial output with OSC/CSI escape
# sequences (shell-integration markers) glued onto the payload line.
csi_re=$'^\e\\[[0-9;?]*[[:alpha:]]'

# Reads serial lines into the log until one matches the pattern.
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

# Waits for the autologin shell, then replaces it with a quiet non-interactive
# bash so no prompt, readline echo, or kernel chatter corrupts the markers.
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
            printf 'qemu-net-lab: %s shell is ready\n' "$name"
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
    printf 'qemu-net-lab: %s ok\n' "$name"
}

"$qemu_bin" "${common_args[@]}" \
    -serial "tcp:127.0.0.1:$fw_serial_port,server=on,wait=on" \
    -netdev "user,id=wan,hostfwd=tcp:127.0.0.1:$wan_probe_port-:22" \
    -device "virtio-net-pci,netdev=wan,mac=52:54:00:0a:00:01,addr=0x4" \
    -netdev "stream,id=lan,server=on,addr.type=inet,addr.host=127.0.0.1,addr.port=$lan_port" \
    -device "virtio-net-pci,netdev=lan,mac=52:54:00:0a:00:02,addr=0x5" \
    &
fw_pid=$!
open_serial "$fw_serial_port" "$fw_pid" || fail 'could not reach the firewall serial port'
fw_fd=$serial_fd

"$qemu_bin" "${common_args[@]}" \
    -serial "tcp:127.0.0.1:$client_serial_port,server=on,wait=on" \
    -netdev "stream,id=lan,server=off,addr.type=inet,addr.host=127.0.0.1,addr.port=$lan_port,reconnect-ms=1000" \
    -device "virtio-net-pci,netdev=lan,mac=52:54:00:0a:00:03,addr=0x4" \
    &
client_pid=$!
open_serial "$client_serial_port" "$client_pid" || fail 'could not reach the client serial port'
client_fd=$serial_fd

wait_shell "$fw_fd" "$fw_pid" "$fw_log" firewall

run_check "$fw_fd" "$fw_pid" "$fw_log" 75 fw-wan-dhcp \
    'for i in $(seq 60); do ip -4 addr show dev eth0 2>/dev/null | grep -q "inet 10.0.2." && break; sleep 1; done; ip -4 addr show dev eth0 | grep -q "inet 10.0.2."'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-ip-forward \
    '[ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ]'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-nftables-applied \
    '[ "$(systemctl show -p Result --value nftables)" = success ]'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-input-default-deny \
    'nft list chain inet filter input | grep -q "policy drop"'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-nat-masquerade \
    'nft list ruleset | grep -q masquerade'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-dnsmasq-active \
    'systemctl is-active --quiet dnsmasq'
run_check "$fw_fd" "$fw_pid" "$fw_log" 10 fw-sshd-active \
    'systemctl is-active --quiet sshd'

wait_shell "$client_fd" "$client_pid" "$client_log" client

run_check "$client_fd" "$client_pid" "$client_log" 105 client-lan-dhcp \
    'for i in $(seq 90); do ip -4 addr show dev eth0 2>/dev/null | grep -q "inet 10.10.10." && break; sleep 1; done; ip -4 addr show dev eth0 | grep -q "inet 10.10.10."'
run_check "$client_fd" "$client_pid" "$client_log" 10 client-default-route \
    'ip route show default | grep -q "via 10.10.10.1"'
run_check "$client_fd" "$client_pid" "$client_log" 45 client-dns \
    'for i in $(seq 10); do getent hosts fwos.lan | grep -q 10.10.10.1 && break; sleep 2; done; getent hosts fwos.lan | grep -q 10.10.10.1'
run_check "$client_fd" "$client_pid" "$client_log" 60 client-wan-nat \
    "for i in \$(seq 3); do curl -sf --max-time 15 http://10.0.2.2:$http_port/ && break; sleep 2; done; curl -sf --max-time 15 http://10.0.2.2:$http_port/"
run_check "$client_fd" "$client_pid" "$client_log" 15 client-lan-ssh-banner \
    'timeout 5 bash -c "head -c4 </dev/tcp/10.10.10.1/22" | grep -q SSH-'

if timeout 5 bash -c "head -c4 </dev/tcp/127.0.0.1/$wan_probe_port" 2>/dev/null | grep -q SSH-; then
    fail 'unsolicited WAN ingress reached sshd; default-deny is broken'
fi
printf 'qemu-net-lab: wan-ingress-blocked ok\n'

printf 'qemu-net-lab: all checks passed\n'
