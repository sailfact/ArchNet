# fwOS

fwOS is an Arch-based firewall/router appliance. Phase 2 provides a basic live firewall image with the default topology: WAN on `eth0` (DHCP client), LAN on `eth1` (`10.10.10.1/24`, DHCP `10.10.10.100`–`10.10.10.200`), dnsmasq DHCP+DNS on the LAN, IPv4 forwarding with NAT, and a default-deny nftables policy for unsolicited WAN ingress.

The Phase 2 service configurations under `airootfs/etc/` (nftables, dnsmasq, systemd-networkd, sshd, sysctl) are interim static build inputs. The Phase 3 config engine will render them from `/etc/project/config.yaml`; do not hand-edit them on a running system.

## Access

- Console logins (tty1 and ttyS0) are automatic.
- SSH is reachable from the LAN only, as `root` with the interim default password `fwos`. The firewall drops SSH from the WAN.

## Host requirements

Use an x86_64 Arch Linux development host with `archiso` 88-1, `grub`, `qemu-desktop`, `edk2-ovmf`, `make`, `python3`, and `sudo`. Install or update those packages only through the host's approved snapshot/update process; this repository never performs a system upgrade.

## Build

```sh
make iso
```

The pinned ISO is written to `_out/fwos-2026.07.10-x86_64.iso`. A failed build leaves `_work/` intact; inspect mount bindings before removing it manually.

## Verify

```sh
make test
```

This runs the profile contract test, boots the ISO headlessly through BIOS and UEFI, and then runs the QEMU network lab: a firewall VM (WAN on QEMU user-mode networking, LAN on a stream socket) plus a LAN client VM booted from the same ISO. The lab verifies the WAN DHCP lease, IPv4 forwarding, the nftables default-deny and NAT rules, the client's dnsmasq lease, default route, DNS through the firewall (`fwos.lan`), LAN→WAN NAT reachability, LAN-only SSH, and that unsolicited WAN ingress is dropped. Serial logs are preserved under `_out/test-logs/`.

For an interactive UEFI or BIOS boot:

```sh
make qemu
make qemu-bios
```

## Physical UEFI validation

Physical UEFI validation has not been recorded. When hardware is available, boot the unchanged ISO, verify that it reaches the `fwos` local console, and record the machine model, firmware mode, ISO checksum, and result before claiming the hardware gate.
