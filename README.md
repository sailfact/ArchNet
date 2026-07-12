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
