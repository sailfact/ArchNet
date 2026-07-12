#!/usr/bin/env bash
set -euo pipefail

fail() {
    printf 'qemu-smoke: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 2 ]] || fail 'usage: qemu-smoke.sh <bios|uefi> <iso-path>'
mode="$1"
iso="$2"
[[ "$mode" == 'bios' || "$mode" == 'uefi' ]] || fail "invalid mode: $mode"
[[ -f "$iso" ]] || fail "missing ISO: $iso"

qemu_bin="${QEMU_BIN:-qemu-system-x86_64}"
ovmf_code="${OVMF_CODE:-/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd}"
ovmf_vars="${OVMF_VARS:-/usr/share/edk2/x64/OVMF_VARS.4m.fd}"
boot_timeout="${BOOT_TIMEOUT:-60}"
output_dir="${OUTPUT_DIR:-$(dirname "$iso")/test-logs}"
[[ "$boot_timeout" =~ ^[1-9][0-9]*$ ]] || fail 'BOOT_TIMEOUT must be a positive integer'

if [[ "$qemu_bin" == */* ]]; then
    [[ -x "$qemu_bin" ]] || fail "QEMU is not executable: $qemu_bin"
else
    command -v "$qemu_bin" >/dev/null || fail "missing QEMU command: $qemu_bin"
fi

mkdir -p "$output_dir"
log="$output_dir/qemu-$mode.log"
: >"$log"
tmpdir="$(mktemp -d)"
pid=''

cleanup() {
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    rm -rf "$tmpdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

accel='tcg'
[[ -r /dev/kvm && -w /dev/kvm ]] && accel='kvm'
qemu_args=(
    -machine q35
    -accel "$accel"
    -m 1024
    -smp 2
    -boot order=d
    -cdrom "$iso"
    -display none
    -monitor none
    -serial "file:$log"
    -no-reboot
)

if [[ "$mode" == 'uefi' ]]; then
    [[ -f "$ovmf_code" ]] || fail "missing OVMF code: $ovmf_code"
    [[ -f "$ovmf_vars" ]] || fail "missing OVMF vars: $ovmf_vars"
    cp "$ovmf_vars" "$tmpdir/OVMF_VARS.4m.fd"
    qemu_args+=(
        -drive "if=pflash,format=raw,unit=0,file=$ovmf_code,readonly=on"
        -drive "if=pflash,format=raw,unit=1,file=$tmpdir/OVMF_VARS.4m.fd"
        -global driver=cfi.pflash01,property=secure,value=off
    )
fi

"$qemu_bin" "${qemu_args[@]}" &
pid=$!

for ((second = 0; second < boot_timeout; second++)); do
    if grep -Fq 'fwos login:' "$log"; then
        printf 'qemu-smoke: %s boot reached fwos login\n' "$mode"
        exit 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        status=0
        wait "$pid" || status=$?
        pid=''
        fail "$mode QEMU exited before login with status $status; see $log"
    fi
    sleep 1
done

fail "$mode boot timed out after ${boot_timeout}s; see $log"
