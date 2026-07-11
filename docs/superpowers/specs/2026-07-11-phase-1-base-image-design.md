# Phase 1 Base Arch Image Design

**Status:** Approved on 2026-07-11

## Goal

Produce the smallest reproducible fwOS live ISO that boots through BIOS and UEFI in QEMU, exposes a local recovery console, and contains the Phase 1 system stack without activating Phase 2 network or firewall behavior.

## Decisions

- Build locally for the MVP; defer cloud ISO builds.
- Keep the MVP base mutable; defer semi-immutable behavior to Phase 17.
- Customize Archiso's `baseline` profile and commit the complete profile at the repository root.
- Base the profile on Archiso `88-1`; treat that as the only verified build-tool version for Phase 1.
- Treat automated BIOS and UEFI QEMU boots as the Phase 1 software gate. Record physical UEFI validation separately after the ISO is available.
- Pin image packages to the Arch Linux Archive snapshot dated `2026-07-10`.
- Use `fwos` as the Phase 1 hostname while the product name remains a working name.

## Repository Shape

Keep Archiso profile inputs at the repository root:

- `profiledef.sh` defines the fwOS ISO and both boot modes.
- `packages.x86_64` contains the complete image package manifest.
- `pacman.conf` points only at the pinned Arch Linux Archive repositories.
- `airootfs/` contains hostname, MOTD, console, service-enablement, and recovery files copied into the live image.
- Archiso boot directories contain the committed BIOS and UEFI baseline configuration plus fwOS identity, serial-console parameters, and recovery entries.
- `Makefile` is the sole build and QEMU entrypoint.
- `scripts/qemu-smoke.sh` contains the shared headless boot probe.
- `tests/phase1-profile.sh` checks static Phase 1 invariants.
- `README.md` documents only commands that exist.

Delete the broken GitHub Actions ISO workflow and the dummy-interface Docker runtime. Do not add replacement CI or Docker support during Phase 1.

## Image Contents

Start with the packages required by the supported Archiso baseline. Add the Phase 1 stack:

- `nftables`
- `dnsmasq`
- `openssh`
- `curl`
- `jq`
- `vim`
- the network and boot utilities required by the baseline profile

Do not include desktop packages, duplicate editors, VirtualBox/VMware guest tools, or QEMU guest agents.

`systemd` supplies systemd-networkd and systemd-resolved. Enable those services and local/serial consoles. Install but do not enable `nftables`, `dnsmasq`, or `sshd`: Phase 1 has no validated config model, firewall policy, LAN boundary, or rendered service configuration.

Set `/etc/hostname` to `fwos`. Make the MOTD state that this is a Phase 1 base image with no active firewall policy. Permit root access on local consoles only; expose no remote login. Add a normal boot entry and a recovery entry using systemd's rescue target for both BIOS and UEFI.

Do not add systemd-networkd units, nftables rules, dnsmasq configuration, interface assignments, DHCP, DNS forwarding, NAT, or SSH exposure. Later phases must render those files from `/etc/project/config.yaml` through the state machine.

## Build Flow

`make iso` performs preflight checks, then runs `mkarchiso` against the repository root. It writes the ISO to `_out/` and temporary state to an ignored work directory. It uses a fixed source date matching the repository snapshot so the output name and timestamps do not vary between equivalent builds.

The build fails before mutation when required host tools are missing, Archiso is not version `88-1`, the package repositories are not pinned, or root privileges are unavailable. It never performs a pacman upgrade or silently changes the selected snapshot.

Do not provide an automatic cleanup target. Let `mkarchiso` remove its work directory only after a successful build; preserve failed work state so mount bindings can be inspected safely.

## QEMU and Test Flow

- `make qemu` boots an existing ISO interactively through UEFI.
- `make qemu-bios` boots the same ISO interactively through legacy BIOS.
- `make test` requires an existing ISO, runs `tests/phase1-profile.sh`, then runs the shared smoke probe once per firmware mode.

The static test verifies:

- shell syntax;
- the fixed archive snapshot;
- required and excluded packages;
- hostname and MOTD content;
- safe service enablement;
- normal and rescue boot entries;
- serial-console kernel parameters.

The QEMU probe starts a headless VM with at least 1 GiB RAM, captures its serial console, and waits up to 60 seconds for `fwos login:`. It terminates the VM immediately after that marker. It fails on timeout, early QEMU exit, a missing ISO, missing QEMU/OVMF tooling, or a missing marker. Preserve BIOS and UEFI serial logs under ignored build output for diagnosis.

## Acceptance Criteria

Phase 1 software work passes when all of these are true:

1. `make iso` builds the pinned mutable image without a blind system upgrade.
2. `make test` passes the static profile checks and both QEMU firmware probes.
3. `make qemu` reaches the fwOS local console through UEFI.
4. The image contains every Phase 1 package and no desktop or hypervisor-guest package.
5. Only safe base services are enabled; no firewall, DHCP/DNS, or remote-management configuration is active.
6. The hostname, MOTD, and local rescue entry are present.
7. README commands match the implemented Make targets.
8. README records physical UEFI validation as a manual follow-up, not as an automated result.

## Excluded Work

Keep these out of Phase 1:

- firewall rules and NAT;
- WAN/LAN assignments and networkd units;
- DHCP or DNS configuration;
- `/etc/project/config.yaml`, its schema, renderers, and apply state machine;
- `fwctl`;
- installer behavior;
- multi-VM network topology;
- cloud CI, Docker build hosting, signing, packaging, and release channels.
