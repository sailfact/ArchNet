#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() {
    printf 'phase1-profile: %s\n' "$*" >&2
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
    profiledef.sh packages.x86_64 pacman.conf \
    airootfs/etc/hostname airootfs/etc/locale.conf airootfs/etc/motd \
    airootfs/etc/shadow airootfs/etc/mkinitcpio.conf.d/archiso.conf \
    airootfs/etc/mkinitcpio.d/linux.preset \
    syslinux/syslinux.cfg syslinux/syslinux-linux.cfg \
    grub/grub.cfg grub/loopback.cfg
do
    assert_file "$file"
done

bash -n profiledef.sh
assert_contains profiledef.sh 'iso_name="fwos"'
assert_contains profiledef.sh "'bios.syslinux'"
assert_contains profiledef.sh "'uefi.grub'"
assert_contains profiledef.sh 'airootfs_image_type="erofs"'

required_packages=(
    amd-ucode base curl dnsmasq intel-ucode iproute2 jq linux linux-firmware
    mkinitcpio mkinitcpio-archiso nftables openssh pv syslinux vim
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
assert_contains airootfs/etc/motd 'no active firewall policy'
grep -Fxq 'root::14871::::::' airootfs/etc/shadow || fail 'local root console is unavailable'

assert_link airootfs/etc/localtime /usr/share/zoneinfo/UTC
assert_link airootfs/etc/systemd/system-generators/systemd-gpt-auto-generator /dev/null
assert_link airootfs/etc/systemd/system/multi-user.target.wants/systemd-networkd.service /usr/lib/systemd/system/systemd-networkd.service
assert_link airootfs/etc/systemd/system/multi-user.target.wants/systemd-resolved.service /usr/lib/systemd/system/systemd-resolved.service
assert_link airootfs/etc/systemd/system/sockets.target.wants/systemd-networkd.socket /usr/lib/systemd/system/systemd-networkd.socket

for path in \
    airootfs/etc/systemd/network \
    airootfs/etc/systemd/system/multi-user.target.wants/dnsmasq.service \
    airootfs/etc/systemd/system/multi-user.target.wants/nftables.service \
    airootfs/etc/systemd/system/multi-user.target.wants/sshd.service \
    airootfs/etc/systemd/system/network-online.target.wants \
    airootfs/etc/ssh \
    airootfs/etc/dnsmasq.conf \
    airootfs/etc/nftables.conf
do
    assert_absent "$path"
done

for file in syslinux/syslinux-linux.cfg grub/grub.cfg grub/loopback.cfg; do
    assert_contains "$file" 'fwOS'
    assert_contains "$file" 'console=tty0 console=ttyS0,115200n8'
    assert_contains "$file" 'systemd.unit=rescue.target'
done

printf 'phase1-profile: ok\n'
