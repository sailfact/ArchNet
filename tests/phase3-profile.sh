#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() {
    printf 'phase3-profile: %s\n' "$*" >&2
    exit 1
}

assert_file() {
    [[ -f "$1" ]] || fail "missing file: $1"
}

assert_contains() {
    grep -Fq -- "$2" "$1" || fail "$1 does not contain: $2"
}

assert_absent() {
    [[ ! -e "$1" && ! -L "$1" ]] || fail "must be absent: $1"
}

assert_link() {
    [[ -L "$1" ]] || fail "missing symlink: $1"
    [[ "$(readlink "$1")" == "$2" ]] || fail "wrong symlink target: $1"
}

for file in \
    profiledef.sh packages.x86_64 pacman.conf pytest.ini \
    config/schema.json config/example-config.yaml \
    core/pyproject.toml core/fwos_core/model.py core/fwos_core/validate.py \
    core/fwos_core/render/nftables.py core/fwos_core/apply/machine.py \
    cli/pyproject.toml cli/fwos_cli/main.py \
    scripts/stage-airootfs.sh airootfs/usr/local/bin/fwctl \
    airootfs/etc/hostname airootfs/etc/locale.conf airootfs/etc/motd \
    airootfs/etc/shadow airootfs/etc/mkinitcpio.conf.d/archiso.conf \
    airootfs/etc/mkinitcpio.d/linux.preset \
    airootfs/etc/sysctl.d/20-fwos-router.conf \
    airootfs/etc/ssh/sshd_config.d/10-fwos.conf \
    airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf \
    airootfs/etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf \
    syslinux/syslinux.cfg syslinux/syslinux-linux.cfg \
    grub/grub.cfg grub/loopback.cfg
do
    assert_file "$file"
done

# Staged build output (gitignored) must exist and match the sources; run
# `make stage` (or scripts/stage-airootfs.sh) before this test.
for file in \
    airootfs/etc/project/config.yaml \
    airootfs/var/lib/project/committed-config.yaml \
    airootfs/usr/lib/fwos/schema.json \
    airootfs/usr/lib/fwos/fwos_core/model.py \
    airootfs/usr/lib/fwos/fwos_cli/main.py \
    airootfs/etc/nftables.conf airootfs/etc/dnsmasq.conf \
    airootfs/etc/systemd/network/20-wan.network \
    airootfs/etc/systemd/network/30-lan.network
do
    [[ -f "$file" ]] || fail "missing staged file (run make stage): $file"
done

diff -r -x __pycache__ core/fwos_core airootfs/usr/lib/fwos/fwos_core >/dev/null ||
    fail 'staged fwos_core differs from core/fwos_core; rerun make stage'
diff -r -x __pycache__ cli/fwos_cli airootfs/usr/lib/fwos/fwos_cli >/dev/null ||
    fail 'staged fwos_cli differs from cli/fwos_cli; rerun make stage'
cmp -s config/schema.json airootfs/usr/lib/fwos/schema.json ||
    fail 'staged schema.json differs from config/schema.json; rerun make stage'
cmp -s config/example-config.yaml airootfs/etc/project/config.yaml ||
    fail 'staged config.yaml differs from config/example-config.yaml; rerun make stage'
cmp -s config/example-config.yaml airootfs/var/lib/project/committed-config.yaml ||
    fail 'staged committed-config.yaml differs; rerun make stage'

bash -n profiledef.sh
assert_contains profiledef.sh 'iso_name="fwos"'
assert_contains profiledef.sh "'bios.syslinux'"
assert_contains profiledef.sh "'uefi.grub'"
assert_contains profiledef.sh 'airootfs_image_type="erofs"'
assert_contains profiledef.sh '["/usr/local/bin/fwctl"]="0:0:755"'
metadata="$(
    TZ=America/Los_Angeles SOURCE_DATE_EPOCH=1783641600 bash -c '
        declare -A file_permissions=()
        source profiledef.sh
        printf "%s %s" "$iso_label" "$iso_version"
    '
)"
[[ "$metadata" == 'FWOS_20260710 2026.07.10' ]] ||
    fail "metadata mismatch: expected FWOS_20260710 2026.07.10, got $metadata"

required_packages=(
    amd-ucode base curl dnsmasq intel-ucode iproute2 jq linux linux-firmware
    mkinitcpio mkinitcpio-archiso nftables openssh pv python python-jsonschema
    python-yaml syslinux vim
)
excluded_packages=(
    cloud-init hyperv neovim open-vm-tools qemu-guest-agent
    virtualbox-guest-utils-nox
)

for package in "${required_packages[@]}"; do
    grep -Fxq "$package" packages.x86_64 || fail "missing package: $package"
done
for package in "${excluded_packages[@]}"; do
    ! grep -Fxq "$package" packages.x86_64 || fail "excluded package: $package"
done
[[ -z "$(sort packages.x86_64 | uniq -d)" ]] || fail 'duplicate package'
diff -u <(sort packages.x86_64) packages.x86_64 >/dev/null || fail 'packages must be sorted'

archive_url='https://archive.archlinux.org/repos/2026/07/10/$repo/os/$arch'
[[ "$(grep -Fxc "Server = $archive_url" pacman.conf)" -eq 2 ]] || fail 'both repositories must use the fixed archive'
[[ "$(grep -c '^Server = ' pacman.conf)" -eq 2 ]] || fail 'unexpected package repository'
! grep -Fq 'mirrorlist' pacman.conf || fail 'pacman.conf must not use live mirrors'

[[ "$(<airootfs/etc/hostname)" == 'fwos' ]] || fail 'hostname must be fwos'
assert_contains airootfs/etc/motd 'default-deny unsolicited WAN ingress'
assert_contains airootfs/etc/motd 'root / fwos'
grep -Eq '^root:\$6\$[^:]+:14871::::::$' airootfs/etc/shadow || fail 'root must have a hashed password for LAN SSH'
! grep -Eq '^root::' airootfs/etc/shadow || fail 'root must not have an empty password'

assert_link airootfs/etc/localtime /usr/share/zoneinfo/UTC
assert_link airootfs/etc/resolv.conf /run/systemd/resolve/stub-resolv.conf
assert_link airootfs/etc/systemd/system-generators/systemd-gpt-auto-generator /dev/null
assert_link airootfs/etc/systemd/system/multi-user.target.wants/systemd-networkd.service /usr/lib/systemd/system/systemd-networkd.service
assert_link airootfs/etc/systemd/system/multi-user.target.wants/systemd-resolved.service /usr/lib/systemd/system/systemd-resolved.service
assert_link airootfs/etc/systemd/system/sockets.target.wants/systemd-networkd.socket /usr/lib/systemd/system/systemd-networkd.socket
assert_link airootfs/etc/systemd/system/multi-user.target.wants/nftables.service /usr/lib/systemd/system/nftables.service
assert_link airootfs/etc/systemd/system/multi-user.target.wants/dnsmasq.service /usr/lib/systemd/system/dnsmasq.service
assert_link airootfs/etc/systemd/system/multi-user.target.wants/sshd.service /usr/lib/systemd/system/sshd.service

# Rendered service files: generated by the config engine, never committed.
generated_banner='Generated by the fwOS config engine'
for file in \
    airootfs/etc/nftables.conf airootfs/etc/dnsmasq.conf \
    airootfs/etc/systemd/network/20-wan.network \
    airootfs/etc/systemd/network/30-lan.network
do
    assert_contains "$file" "$generated_banner"
done
if git rev-parse --git-dir >/dev/null 2>&1; then
    tracked="$(git ls-files -- airootfs/etc/nftables.conf airootfs/etc/dnsmasq.conf \
        'airootfs/etc/systemd/network/*.network' airootfs/etc/project \
        airootfs/usr/lib/fwos airootfs/var/lib/project)"
    [[ -z "$tracked" ]] || fail "rendered/staged files must not be tracked: $tracked"
fi

assert_contains airootfs/etc/systemd/network/20-wan.network 'Name=eth0'
assert_contains airootfs/etc/systemd/network/20-wan.network 'DHCP=ipv4'
assert_contains airootfs/etc/systemd/network/30-lan.network 'Name=eth1'
assert_contains airootfs/etc/systemd/network/30-lan.network 'Address=10.10.10.1/24'
assert_contains airootfs/etc/sysctl.d/20-fwos-router.conf 'net.ipv4.ip_forward = 1'

assert_contains airootfs/etc/nftables.conf 'flush ruleset'
assert_contains airootfs/etc/nftables.conf 'define wan_if = "eth0"'
assert_contains airootfs/etc/nftables.conf 'define lan_if = "eth1"'
[[ "$(grep -Fc 'policy drop;' airootfs/etc/nftables.conf)" -eq 2 ]] || fail 'input and forward chains must default-deny'
assert_contains airootfs/etc/nftables.conf 'oifname $wan_if masquerade'
if command -v nft >/dev/null && command -v unshare >/dev/null; then
    # Root creates the scratch netns directly; a mapped user namespace would
    # unmap the repository owner and break path resolution under their home.
    if [[ "$EUID" -eq 0 ]]; then
        unshare --net nft --check -f airootfs/etc/nftables.conf ||
            fail 'nftables.conf failed nft --check'
    else
        unshare --map-root-user --net nft --check -f airootfs/etc/nftables.conf ||
            fail 'nftables.conf failed nft --check'
    fi
fi

assert_contains airootfs/etc/dnsmasq.conf 'interface=eth1'
assert_contains airootfs/etc/dnsmasq.conf 'dhcp-range=10.10.10.100,10.10.10.200,12h'
assert_contains airootfs/etc/dnsmasq.conf 'dhcp-option=option:router,10.10.10.1'
assert_contains airootfs/etc/dnsmasq.conf 'resolv-file=/run/systemd/resolve/resolv.conf'
if command -v dnsmasq >/dev/null; then
    dnsmasq --test --conf-file=airootfs/etc/dnsmasq.conf >/dev/null 2>&1 ||
        fail 'dnsmasq.conf failed dnsmasq --test'
fi

assert_contains airootfs/usr/local/bin/fwctl 'python -m fwos_cli'
assert_contains airootfs/usr/local/bin/fwctl 'PYTHONPATH=/usr/lib/fwos'
assert_contains config/schema.json '"const": 1'
assert_contains config/example-config.yaml 'version: 1'
for entry in '/airootfs/usr/lib/fwos/' '/airootfs/etc/project/' \
    '/airootfs/var/lib/project/' '/airootfs/etc/nftables.conf' \
    '/airootfs/etc/dnsmasq.conf' '/airootfs/etc/systemd/network/*.network' \
    '__pycache__/'
do
    assert_contains .gitignore "$entry"
done

assert_contains airootfs/etc/ssh/sshd_config.d/10-fwos.conf 'PermitRootLogin yes'
assert_contains airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf '--autologin root'
assert_contains airootfs/etc/systemd/system/serial-getty@ttyS0.service.d/autologin.conf '--autologin root'

for file in syslinux/syslinux-linux.cfg grub/grub.cfg grub/loopback.cfg; do
    assert_contains "$file" 'fwOS'
    assert_contains "$file" 'console=tty0 console=ttyS0,115200n8 net.ifnames=0'
    assert_contains "$file" 'systemd.unit=rescue.target'
done

for target in iso qemu qemu-bios test stage check; do
    make -n "$target" >/dev/null || fail "broken Make target: $target"
done
bash -n profiledef.sh scripts/qemu-smoke.sh scripts/qemu-net-lab.sh \
    scripts/qemu-config-lab.sh scripts/stage-airootfs.sh \
    airootfs/usr/local/bin/fwctl \
    tests/phase3-profile.sh tests/qemu-smoke.sh tests/qemu-net-lab.sh \
    tests/qemu-config-lab.sh

for path in Dockerfile entrypoint.sh .github/workflows/build.yml packages.txt \
    tests/phase1-profile.sh tests/phase2-profile.sh
do
    assert_absent "$path"
done

assert_file README.md
assert_file CHANGELOG.md
assert_file AGENTS.md
assert_link CLAUDE.md AGENTS.md
for command in 'make iso' 'make test' 'make qemu' 'make qemu-bios'; do
    assert_contains README.md "$command"
done
assert_contains README.md 'default password `fwos`'
assert_contains AGENTS.md '`make qemu`'

if grep -R -E 'pacman[[:space:]]+-S(yu|yyu)' README.md Makefile .github 2>/dev/null; then
    fail 'blind pacman upgrade command found'
fi
if grep -Eq '^clean:' Makefile; then
    fail 'unsafe clean target found'
fi

printf 'phase3-profile: ok\n'
