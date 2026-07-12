#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

touch "$tmpdir/fwos.iso" "$tmpdir/OVMF_CODE.fd" "$tmpdir/OVMF_VARS.fd"
cat >"$tmpdir/fake-qemu" <<'FAKE_QEMU'
#!/usr/bin/env bash
set -euo pipefail
log=''
while (($#)); do
    if [[ "$1" == '-serial' ]]; then
        shift
        log="${1#file:}"
    fi
    shift
done
[[ -n "$log" ]]
printf 'fwos login:\n' >"$log"
while :; do sleep 1; done
FAKE_QEMU
chmod +x "$tmpdir/fake-qemu"

for mode in bios uefi; do
    QEMU_BIN="$tmpdir/fake-qemu" \
    OVMF_CODE="$tmpdir/OVMF_CODE.fd" \
    OVMF_VARS="$tmpdir/OVMF_VARS.fd" \
    BOOT_TIMEOUT=3 \
    OUTPUT_DIR="$tmpdir/logs" \
      ./scripts/qemu-smoke.sh "$mode" "$tmpdir/fwos.iso"
    grep -Fq 'fwos login:' "$tmpdir/logs/qemu-$mode.log"
done

if ./scripts/qemu-smoke.sh invalid "$tmpdir/fwos.iso" 2>/dev/null; then
    printf 'qemu-smoke-test: invalid mode succeeded\n' >&2
    exit 1
fi

printf 'qemu-smoke-test: ok\n'
