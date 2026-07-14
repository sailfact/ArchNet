#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

touch "$tmpdir/fwos.iso"

if ./scripts/qemu-config-lab.sh 2>/dev/null; then
    printf 'qemu-config-lab-test: missing ISO argument succeeded\n' >&2
    exit 1
fi

if ./scripts/qemu-config-lab.sh "$tmpdir/missing.iso" 2>/dev/null; then
    printf 'qemu-config-lab-test: nonexistent ISO succeeded\n' >&2
    exit 1
fi

if BOOT_TIMEOUT=soon ./scripts/qemu-config-lab.sh "$tmpdir/fwos.iso" 2>/dev/null; then
    printf 'qemu-config-lab-test: invalid BOOT_TIMEOUT succeeded\n' >&2
    exit 1
fi

if LAB_PORT_BASE=high ./scripts/qemu-config-lab.sh "$tmpdir/fwos.iso" 2>/dev/null; then
    printf 'qemu-config-lab-test: invalid LAB_PORT_BASE succeeded\n' >&2
    exit 1
fi

printf 'qemu-config-lab-test: ok\n'
