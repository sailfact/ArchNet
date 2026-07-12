# Phase 1 Base Arch Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a pinned, mutable fwOS Phase 1 live ISO that reaches a local console through BIOS and UEFI without activating firewall, DHCP/DNS, or remote-management behavior.

**Architecture:** Commit the minimal required pieces of Archiso 88-1's `baseline` profile at the repository root, replacing its DHCP, SSH, cloud-init, and hypervisor defaults with fwOS-safe local-console behavior. A Makefile owns build and interactive boot commands; one static shell test protects the profile contract and one small QEMU runner probes both firmware paths over the serial console.

**Tech Stack:** Bash, GNU Make, Archiso 88-1, pacman with Arch Linux Archive snapshot `2026-07-10`, QEMU, GRUB, Syslinux, OVMF, systemd.

## Global Constraints

- Keep the Archiso profile at the repository root.
- Use `2026-07-10` (`SOURCE_DATE_EPOCH=1783641600`) for package repositories and deterministic image metadata.
- Support only `bios.syslinux` and `uefi.grub` in Phase 1.
- Never enable `nftables`, `dnsmasq`, or `sshd` in Phase 1.
- Never add networkd units, nftables rules, dnsmasq configuration, WAN/LAN assignments, or remote login.
- Never run or document a blind full-system pacman upgrade.
- Preserve failed Archiso work directories; do not add an automatic cleanup target.
- Keep cloud CI, Docker build hosting, the config engine, `fwctl`, the installer, and network topology out of this plan.

---

## File Map

- `profiledef.sh`: Archiso identity, image format, and BIOS/UEFI modes.
- `packages.x86_64`: Exact live-image package manifest.
- `pacman.conf`: Fixed Arch Linux Archive repositories.
- `airootfs/etc/*`: Live hostname, warning, root console, initramfs, locale, and safe service enablement.
- `syslinux/*`: BIOS normal and recovery entries.
- `grub/*`: UEFI and loopback normal and recovery entries.
- `tests/phase1-profile.sh`: Static profile and repository contract.
- `scripts/qemu-smoke.sh`: Headless BIOS/UEFI boot probe.
- `tests/qemu-smoke.sh`: Fake-QEMU check for the probe's branching and cleanup.
- `Makefile`: Build, interactive boot, and complete test entrypoints.
- `README.md`, `CHANGELOG.md`, `AGENTS.md`: Verified commands, release note, and current agent guidance.
- `.gitignore`: Build/work output only.
- `Dockerfile`, `entrypoint.sh`, `.github/workflows/build.yml`, `packages.txt`: Remove obsolete or conflicting paths.

---

### Task 1: Commit the safe Archiso profile

**Files:**
- Modify: `profiledef.sh`
- Delete: `packages.txt`
- Create: `packages.x86_64`
- Create: `pacman.conf`
- Create: `airootfs/etc/hostname`
- Create: `airootfs/etc/locale.conf`
- Create: `airootfs/etc/motd`
- Create: `airootfs/etc/shadow`
- Create: `airootfs/etc/mkinitcpio.conf.d/archiso.conf`
- Create: `airootfs/etc/mkinitcpio.d/linux.preset`
- Create symlinks under: `airootfs/etc/systemd/`
- Create: `syslinux/syslinux.cfg`
- Create: `syslinux/syslinux-linux.cfg`
- Create: `grub/grub.cfg`
- Create: `grub/loopback.cfg`
- Test: `tests/phase1-profile.sh`

**Interfaces:**
- Consumes: Archiso 88-1 template tokens `%ARCH%`, `%INSTALL_DIR%`, and `%ARCHISO_UUID%`.
- Produces: A complete root-level profile accepted by `mkarchiso` with ISO path `_out/fwos-2026.07.10-x86_64.iso` when `SOURCE_DATE_EPOCH=1783641600`.

- [ ] **Step 1: Write the failing static profile test**

Create `tests/phase1-profile.sh`:

```bash
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
chmod +x tests/phase1-profile.sh
./tests/phase1-profile.sh
```

Expected: FAIL with `phase1-profile: missing file: packages.x86_64`.

- [ ] **Step 3: Replace the incomplete profile with the minimal Archiso 88-1 profile**

Replace `profiledef.sh` with:

```bash
#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="fwos"
iso_label="FWOS_$(date --utc --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m%d)"
iso_publisher="fwOS project"
iso_application="fwOS Phase 1 base image"
iso_version="$(date --utc --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="fwos"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.grub')
pacman_conf="pacman.conf"
airootfs_image_type="erofs"
airootfs_image_tool_options=('-zlzma,109' -E 'ztailpacking')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
)
```

Create `packages.x86_64` and delete `packages.txt`:

```text
amd-ucode
base
curl
dnsmasq
intel-ucode
iproute2
jq
linux
linux-firmware
mkinitcpio
mkinitcpio-archiso
nftables
openssh
pv
syslinux
vim
```

Create `pacman.conf`:

```ini
[options]
Architecture = auto
ParallelDownloads = 5
SigLevel = Required DatabaseOptional
LocalFileSigLevel = Optional

[core]
Server = https://archive.archlinux.org/repos/2026/07/10/$repo/os/$arch

[extra]
Server = https://archive.archlinux.org/repos/2026/07/10/$repo/os/$arch
```

Create these airootfs files:

`airootfs/etc/hostname`

```text
fwos
```

`airootfs/etc/locale.conf`

```ini
LANG=C.UTF-8
```

`airootfs/etc/motd`

```text
fwOS Phase 1 base image
Warning: this image has no active firewall policy. Use the local console only.
```

`airootfs/etc/shadow`

```text
root::14871::::::
```

`airootfs/etc/mkinitcpio.conf.d/archiso.conf`

```bash
HOOKS=(base udev modconf archiso block filesystems)
```

`airootfs/etc/mkinitcpio.d/linux.preset`

```ini
PRESETS=('archiso')

ALL_kver='/boot/vmlinuz-linux'
archiso_config='/etc/mkinitcpio.conf.d/archiso.conf'
archiso_image='/boot/initramfs-linux.img'
```

Create only the safe baseline symlinks:

```bash
mkdir -p \
  airootfs/etc/systemd/system-generators \
  airootfs/etc/systemd/system/multi-user.target.wants \
  airootfs/etc/systemd/system/sockets.target.wants
ln -s /usr/share/zoneinfo/UTC airootfs/etc/localtime
ln -s /dev/null airootfs/etc/systemd/system-generators/systemd-gpt-auto-generator
ln -s /usr/lib/systemd/system/systemd-networkd.service \
  airootfs/etc/systemd/system/multi-user.target.wants/systemd-networkd.service
ln -s /usr/lib/systemd/system/systemd-resolved.service \
  airootfs/etc/systemd/system/multi-user.target.wants/systemd-resolved.service
ln -s /usr/lib/systemd/system/systemd-networkd.socket \
  airootfs/etc/systemd/system/sockets.target.wants/systemd-networkd.socket
```

Create `syslinux/syslinux.cfg`:

```syslinux
SERIAL 0 115200
UI menu.c32
MENU TITLE fwOS
MENU CLEAR

DEFAULT fwos
TIMEOUT 30

INCLUDE syslinux-linux.cfg
```

Create `syslinux/syslinux-linux.cfg`:

```syslinux
LABEL fwos
MENU LABEL fwOS (%ARCH%, BIOS)
LINUX /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux
INITRD /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% console=tty0 console=ttyS0,115200n8

LABEL fwos-recovery
MENU LABEL fwOS recovery shell (%ARCH%, BIOS)
LINUX /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux
INITRD /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% console=tty0 console=ttyS0,115200n8 systemd.unit=rescue.target
```

Create `grub/grub.cfg`:

```grub
insmod part_gpt
insmod part_msdos
insmod fat
insmod iso9660
insmod serial

if serial --unit=0 --speed=115200; then
    terminal_input --append serial
    terminal_output --append serial
fi

default=fwos
timeout=3
timeout_style=menu

menuentry 'fwOS (x86_64, UEFI)' --id 'fwos' {
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% console=tty0 console=ttyS0,115200n8
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
}

menuentry 'fwOS recovery shell (x86_64, UEFI)' --id 'fwos-recovery' {
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% console=tty0 console=ttyS0,115200n8 systemd.unit=rescue.target
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
}

menuentry 'System shutdown' {
    halt
}

menuentry 'System restart' {
    reboot
}
```

Create `grub/loopback.cfg`:

```grub
search --no-floppy --set=archiso_img_dev --file "${iso_path}"
probe --set archiso_img_dev_uuid --fs-uuid "${archiso_img_dev}"

default=fwos
timeout=3
timeout_style=menu

menuentry 'fwOS (x86_64, loopback)' --id 'fwos' {
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux archisobasedir=%INSTALL_DIR% img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}" console=tty0 console=ttyS0,115200n8
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
}

menuentry 'fwOS recovery shell (x86_64, loopback)' --id 'fwos-recovery' {
    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux archisobasedir=%INSTALL_DIR% img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}" console=tty0 console=ttyS0,115200n8 systemd.unit=rescue.target
    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
}
```

- [ ] **Step 4: Run the static profile test**

Run:

```bash
./tests/phase1-profile.sh
git diff --check
```

Expected: `phase1-profile: ok`; `git diff --check` prints nothing.

- [ ] **Step 5: Commit the profile**

```bash
git add profiledef.sh packages.x86_64 pacman.conf airootfs syslinux grub tests/phase1-profile.sh
git add -u packages.txt
git commit -m "feat: add safe phase 1 archiso profile"
```

---

### Task 2: Add the headless QEMU boot probe

**Files:**
- Create: `scripts/qemu-smoke.sh`
- Create: `tests/qemu-smoke.sh`

**Interfaces:**
- Consumes: `scripts/qemu-smoke.sh <bios|uefi> <iso-path>` plus optional `QEMU_BIN`, `OVMF_CODE`, `OVMF_VARS`, `BOOT_TIMEOUT`, and `OUTPUT_DIR` environment overrides.
- Produces: Exit `0` after `fwos login:` appears; otherwise a non-zero exit and `qemu-<mode>.log`.

- [ ] **Step 1: Write the failing fake-QEMU test**

Create `tests/qemu-smoke.sh`:

```bash
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
chmod +x tests/qemu-smoke.sh
./tests/qemu-smoke.sh
```

Expected: FAIL because `scripts/qemu-smoke.sh` does not exist.

- [ ] **Step 3: Implement the minimal QEMU probe**

Create `scripts/qemu-smoke.sh`:

```bash
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
```

- [ ] **Step 4: Run both shell checks**

Run:

```bash
chmod +x scripts/qemu-smoke.sh
bash -n scripts/qemu-smoke.sh tests/qemu-smoke.sh
./tests/qemu-smoke.sh
./tests/phase1-profile.sh
```

Expected: `qemu-smoke-test: ok` and `phase1-profile: ok`.

- [ ] **Step 5: Commit the probe**

```bash
git add scripts/qemu-smoke.sh tests/qemu-smoke.sh
git commit -m "test: add phase 1 qemu boot probe"
```

---

### Task 3: Make the verified workflow the only workflow

**Files:**
- Create: `Makefile`
- Rewrite: `README.md`
- Create: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Track symlink: `CLAUDE.md`
- Rewrite: `.gitignore`
- Modify: `tests/phase1-profile.sh`
- Delete: `Dockerfile`
- Delete: `entrypoint.sh`
- Delete: `.github/workflows/build.yml`

**Interfaces:**
- Consumes: The profile from Task 1 and `scripts/qemu-smoke.sh` from Task 2.
- Produces: `make iso`, `make qemu`, `make qemu-bios`, and `make test`.

- [ ] **Step 1: Extend the repository contract test before adding the workflow**

Insert this block in `tests/phase1-profile.sh` immediately before its final success message:

```bash
for target in iso qemu qemu-bios test; do
    make -n "$target" >/dev/null || fail "broken Make target: $target"
done
bash -n profiledef.sh scripts/qemu-smoke.sh tests/phase1-profile.sh tests/qemu-smoke.sh

for path in Dockerfile entrypoint.sh .github/workflows/build.yml packages.txt; do
    assert_absent "$path"
done

assert_file README.md
assert_file CHANGELOG.md
assert_file AGENTS.md
assert_link CLAUDE.md AGENTS.md
for command in 'make iso' 'make test' 'make qemu' 'make qemu-bios'; do
    assert_contains README.md "$command"
done
assert_contains AGENTS.md '`make qemu`'

if grep -R -E 'pacman[[:space:]]+-S(yu|yyu)' README.md Makefile .github 2>/dev/null; then
    fail 'blind pacman upgrade command found'
fi
if grep -Eq '^clean:' Makefile; then
    fail 'unsafe clean target found'
fi
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
./tests/phase1-profile.sh
```

Expected: FAIL because no `Makefile` exists.

- [ ] **Step 3: Add the canonical Make targets**

Create `Makefile` with literal tab-indented recipes:

```make
SHELL := /usr/bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ARCHISO_VERSION := 88-1
SOURCE_DATE_EPOCH := 1783641600
OUT_DIR := $(CURDIR)/_out
WORK_DIR := $(CURDIR)/_work
ISO := $(OUT_DIR)/fwos-2026.07.10-x86_64.iso

.PHONY: iso qemu qemu-bios test

iso:
	@command -v pacman >/dev/null || { echo 'make iso: pacman is required' >&2; exit 1; }
	@command -v mkarchiso >/dev/null || { echo 'make iso: archiso is required' >&2; exit 1; }
	@command -v grub-mkstandalone >/dev/null || { echo 'make iso: grub is required' >&2; exit 1; }
	@command -v sudo >/dev/null || { echo 'make iso: sudo is required' >&2; exit 1; }
	@installed="$$(pacman -Q archiso 2>/dev/null || true)"; test "$$installed" = "archiso $(ARCHISO_VERSION)" || { echo 'make iso: archiso 88-1 is required' >&2; exit 1; }
	@test ! -e "$(WORK_DIR)" || { echo 'make iso: _work exists; inspect mounts before removing it' >&2; exit 1; }
	@test ! -e "$(ISO)" || { echo 'make iso: output ISO already exists; move it before rebuilding' >&2; exit 1; }
	@./tests/phase1-profile.sh
	@sudo -v
	@mkdir -p "$(OUT_DIR)"
	sudo env SOURCE_DATE_EPOCH="$(SOURCE_DATE_EPOCH)" mkarchiso -v -r -w "$(WORK_DIR)" -o "$(OUT_DIR)" .

qemu:
	@command -v run_archiso >/dev/null || { echo 'make qemu: archiso is required' >&2; exit 1; }
	@test -f "$(ISO)" || { echo 'make qemu: build the ISO first' >&2; exit 1; }
	run_archiso -u -i "$(ISO)"

qemu-bios:
	@command -v run_archiso >/dev/null || { echo 'make qemu-bios: archiso is required' >&2; exit 1; }
	@test -f "$(ISO)" || { echo 'make qemu-bios: build the ISO first' >&2; exit 1; }
	run_archiso -b -i "$(ISO)"

test:
	@test -f "$(ISO)" || { echo 'make test: build the ISO first' >&2; exit 1; }
	@newer="$$(find Makefile profiledef.sh packages.x86_64 pacman.conf airootfs syslinux grub -newer "$(ISO)" -print -quit)"; test -z "$$newer" || { echo "make test: ISO is older than $$newer; rebuild it" >&2; exit 1; }
	./tests/phase1-profile.sh
	./tests/qemu-smoke.sh
	./scripts/qemu-smoke.sh bios "$(ISO)"
	./scripts/qemu-smoke.sh uefi "$(ISO)"
```

- [ ] **Step 4: Replace obsolete workflows and document only verified commands**

Delete `Dockerfile`, `entrypoint.sh`, and `.github/workflows/build.yml`.

Replace `.gitignore` with:

```gitignore
_out/
_work/
*.iso
*.code-workspace
```

Replace `README.md` with:

```markdown
# fwOS

fwOS is an Arch-based firewall/router appliance. Phase 1 provides a mutable live base image only; it has no active firewall policy, DHCP/DNS configuration, or remote management.

## Host requirements

Use an x86_64 Arch Linux development host with `archiso` 88-1, `grub`, `qemu-desktop`, `edk2-ovmf`, `make`, and `sudo`. Install or update those packages only through the host's approved snapshot/update process; this repository never performs a system upgrade.

## Build

```sh
make iso
```

The pinned ISO is written to `_out/fwos-2026.07.10-x86_64.iso`. A failed build leaves `_work/` intact; inspect mount bindings before removing it manually.

## Verify

```sh
make test
```

The test boots the existing ISO headlessly through BIOS and UEFI and preserves serial logs under `_out/test-logs/`.

For an interactive UEFI or BIOS boot:

```sh
make qemu
make qemu-bios
```

## Physical UEFI validation

Physical UEFI validation has not been recorded. When hardware is available, boot the unchanged ISO, verify that it reaches the `fwos` local console, and record the machine model, firmware mode, ISO checksum, and result before claiming the hardware gate.
```

Create `CHANGELOG.md`:

```markdown
# Changelog

## Unreleased

- Add the pinned fwOS Phase 1 Archiso profile and BIOS/UEFI QEMU smoke tests.
```

In `AGENTS.md`:

- Change the `scripts/` layout line to: ``- `scripts/` contains verified build and QEMU test helpers; never put core product behavior there.``
- Change the `tests/` layout line to: ``- `tests/` contains the Phase 1 profile and QEMU checks; keep production configuration out.``
- Change the QEMU development-loop entrypoint from planned to: `` `make qemu` for interactive UEFI boot; `make test` gates BIOS and UEFI.``
- Replace “No Makefile or script entrypoints exist yet” with: “Use only targets and scripts present in the current tree; mark all others as planned.”

Keep `CLAUDE.md` as a symlink to `AGENTS.md` and track both.

- [ ] **Step 5: Run all non-VM checks**

Run:

```bash
./tests/phase1-profile.sh
./tests/qemu-smoke.sh
make -n iso
make -n qemu
make -n qemu-bios
make -n test
git diff --check
```

Expected: both tests end in `ok`; each dry-run prints its real command; `git diff --check` prints nothing.

- [ ] **Step 6: Commit the workflow and documentation**

```bash
git add Makefile README.md CHANGELOG.md AGENTS.md CLAUDE.md .gitignore tests/phase1-profile.sh
git add -u Dockerfile entrypoint.sh .github/workflows/build.yml
git commit -m "build: add local phase 1 workflow"
```

---

### Task 4: Build and run the real firmware gates

**Files:**
- Generated, ignored: `_out/fwos-2026.07.10-x86_64.iso`
- Generated, ignored: `_out/test-logs/qemu-bios.log`
- Generated, ignored: `_out/test-logs/qemu-uefi.log`

**Interfaces:**
- Consumes: All Phase 1 tracked inputs and the approved local Arch build host.
- Produces: Evidence that both boot modes reach `fwos login:`; no generated artifact is committed.

- [ ] **Step 1: Verify host packages without changing the host**

Run:

```bash
pacman -Q archiso grub qemu-desktop edk2-ovmf make sudo
```

Expected: every package is present and `archiso 88-1` is reported. If packages are missing, obtain approval before installing them with the host's package policy; never add `-Syu` to an installation command.

- [ ] **Step 2: Run the fast checks once more**

Run:

```bash
./tests/phase1-profile.sh
./tests/qemu-smoke.sh
```

Expected: `phase1-profile: ok` and `qemu-smoke-test: ok`.

- [ ] **Step 3: Build the ISO**

Run:

```bash
make iso
```

Expected: `mkarchiso` completes successfully and creates `_out/fwos-2026.07.10-x86_64.iso`; `_work/` is removed by `mkarchiso -r` only after success.

- [ ] **Step 4: Run both real QEMU boot probes**

Run:

```bash
make test
```

Expected final lines include:

```text
qemu-smoke: bios boot reached fwos login
qemu-smoke: uefi boot reached fwos login
```

- [ ] **Step 5: Audit the Phase 1 Definition of Done**

Run:

```bash
git diff --check
git status --short
test -s _out/test-logs/qemu-bios.log
test -s _out/test-logs/qemu-uefi.log
```

Confirm:

- QEMU BIOS and UEFI gates pass.
- Static tests cover the safe service and recovery-entry paths relevant to Phase 1.
- No runtime network/firewall state is written outside the future config model.
- `fwctl`, PKGBUILDs, validation, apply, backup, and rollback are not applicable to this base-image-only phase and were not invented early.
- README and changelog describe the shipped Phase 1 capability.
- Physical UEFI evidence remains explicitly manual and unclaimed.

Expected Git status: only the user's pre-existing unrelated changes, if any; `_out/` and logs remain ignored.
