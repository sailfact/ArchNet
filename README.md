# fwOS

fwOS is an Arch-based firewall/router appliance managed declaratively from a single YAML configuration model. The default topology is: WAN on `eth0` (DHCP client), LAN on `eth1` (`10.10.10.1/24`, DHCP `10.10.10.100`–`10.10.10.200`), dnsmasq DHCP+DNS on the LAN, IPv4 forwarding with NAT, and a default-deny nftables policy for unsolicited WAN ingress.

Since Phase 3, `/etc/project/config.yaml` is the single source of truth. The nftables ruleset, dnsmasq configuration, and systemd-networkd units are rendered from it by the config engine — at ISO build time for the shipped defaults, and by `fwctl apply` on a running system. Never hand-edit the rendered files; they are overwritten on every apply. The sshd and sysctl configurations remain interim static build inputs until the hardening phase.

## Access

- Console logins (tty1 and ttyS0) are automatic.
- SSH is reachable from the LAN only, as `root` with the interim default password `fwos`. The firewall drops SSH from the WAN.

## Configuration

Edit `/etc/project/config.yaml` (interfaces, zones, rules, NAT, DHCP, DNS), then drive the engine with `fwctl`:

```sh
fwctl config validate     # schema + semantic validation only
fwctl config render       # unified diff of rendered files vs the live system
fwctl apply --timeout 120 # validate, render, test, back up, apply
fwctl confirm             # commit within the window, or the change rolls back
fwctl rollback            # restore the latest pre-apply backup on demand
fwctl interfaces          # desired model joined to live interface state
fwctl backup list         # inspect available pre-apply/forensic backups
fwctl backup show ID      # verify and describe one backup
fwctl backup restore ID   # restore through the rollback state machine
fwctl status              # config, pending apply, services, interfaces, backups
```

The original `fwctl validate`, `fwctl render`, and `fwctl rollback [--to ID]`
forms remain supported for automation compatibility. `fwctl` deliberately has
no YAML setters: edit the source model, preview it, then apply it. Safe package
updates are deferred to Phase 7; there is no `fwctl update` command and fwOS
never performs a blind full-system upgrade.

Every apply takes a pre-apply backup and arms a rollback timer *before* touching the system; if `fwctl confirm` does not arrive within the window (default 120 s), the previous configuration and services are restored automatically — the defense against locking yourself out of a remote firewall. Manual rollbacks and timer rollbacks both preserve the discarded state under `/var/lib/project/backups/` for inspection.

All subcommands accept `--json` for automation and return exit codes `0` (ok), `1` (operational failure), `2` (usage), `3` (validation failed), `4` (rendered config rejected by `nft -c`/`dnsmasq --test`). The schema lives at `config/schema.json` in this repository and `/usr/lib/fwos/schema.json` on the appliance; `docs/Config-Model.md` documents the model, the implicit base firewall policy, and the apply state machine.

## Host requirements

Use an x86_64 Arch Linux development host with `archiso` 88-1, `grub`, `qemu-desktop`, `edk2-ovmf`, `make`, `python`, `python-yaml`, `python-jsonschema`, and `sudo`; `python-pytest` is needed for `make check`. Install or update those packages only through the host's approved snapshot/update process; this repository never performs a system upgrade.

## Build

```sh
make iso
```

The build first runs `make stage`, which copies the config engine into `airootfs/usr/lib/fwos/` and renders the default `config/example-config.yaml` into the profile (all staged output is gitignored build product), then writes the pinned ISO to `_out/fwos-2026.07.10-x86_64.iso`. A failed build leaves `_work/` intact; inspect mount bindings before removing it manually.

## Verify

```sh
make check   # config-engine unit tests (schema, renderers, state machine, fwctl)
make test    # full gate: unit tests, profile contract, QEMU labs
```

`make test` runs the unit tests and profile contract test, boots the ISO headlessly through BIOS and UEFI, runs the QEMU network lab (firewall VM plus LAN client VM verifying DHCP, DNS via `fwos.lan`, NAT, LAN-only SSH, and the WAN default-deny), and then the QEMU config lab, which exercises grouped and compatibility CLI forms, live interface/service status, backup inspection and explicit restore, an unconfirmed apply reverted by the rollback timer (the lockout drill), and a confirmed apply. Serial logs are preserved under `_out/test-logs/`.

For an interactive UEFI or BIOS boot:

```sh
make qemu
make qemu-bios
```

## Physical UEFI validation

Physical UEFI validation has not been recorded. When hardware is available, boot the unchanged ISO, verify that it reaches the `fwos` local console, and record the machine model, firmware mode, ISO checksum, and result before claiming the hardware gate.
