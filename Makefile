SHELL := /usr/bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ARCHISO_VERSION := 88-1
SOURCE_DATE_EPOCH := 1783641600
OUT_DIR := $(CURDIR)/_out
WORK_DIR := $(CURDIR)/_work
ISO := $(OUT_DIR)/fwos-2026.07.10-x86_64.iso

.PHONY: iso qemu qemu-bios test stage check

stage:
	@./scripts/stage-airootfs.sh

check:
	@command -v python3 >/dev/null || { echo 'make check: python3 is required' >&2; exit 1; }
	@python3 -c 'import yaml, jsonschema, pytest' 2>/dev/null || { echo 'make check: python-yaml, python-jsonschema and python-pytest are required' >&2; exit 1; }
	python3 -m pytest -q

iso: stage
	@command -v pacman >/dev/null || { echo 'make iso: pacman is required' >&2; exit 1; }
	@command -v mkarchiso >/dev/null || { echo 'make iso: archiso is required' >&2; exit 1; }
	@command -v grub-mkstandalone >/dev/null || { echo 'make iso: grub is required' >&2; exit 1; }
	@command -v sudo >/dev/null || { echo 'make iso: sudo is required' >&2; exit 1; }
	@installed="$$(pacman -Q archiso 2>/dev/null || true)"; test "$$installed" = "archiso $(ARCHISO_VERSION)" || { echo 'make iso: archiso 88-1 is required' >&2; exit 1; }
	@test ! -e "$(WORK_DIR)" || { echo 'make iso: _work exists; inspect mounts before removing it' >&2; exit 1; }
	@test ! -e "$(ISO)" || { echo 'make iso: output ISO already exists; move it before rebuilding' >&2; exit 1; }
	@./tests/phase3-profile.sh
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

test: stage check
	@test -f "$(ISO)" || { echo 'make test: build the ISO first' >&2; exit 1; }
	@newer="$$(find Makefile profiledef.sh packages.x86_64 pacman.conf airootfs syslinux grub core config cli pytest.ini scripts -name __pycache__ -prune -o -newer "$(ISO)" -print -quit)"; test -z "$$newer" || { echo "make test: ISO is older than $$newer; rebuild it" >&2; exit 1; }
	./tests/phase3-profile.sh
	./tests/qemu-smoke.sh
	./tests/qemu-net-lab.sh
	./scripts/qemu-smoke.sh bios "$(ISO)"
	./scripts/qemu-smoke.sh uefi "$(ISO)"
	./scripts/qemu-net-lab.sh "$(ISO)"
