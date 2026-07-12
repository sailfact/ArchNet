# Changelog

## Unreleased

- Add the Phase 2 basic firewall: WAN DHCP on `eth0`, LAN `10.10.10.1/24` on `eth1`, dnsmasq DHCP (`10.10.10.100`–`10.10.10.200`) and DNS forwarding, IPv4 forwarding, and a default-deny nftables policy with LAN→WAN NAT. SSH is enabled for the LAN only (interim `root`/`fwos` credentials); console logins are automatic. Interface names are fixed via `net.ifnames=0`.
- Add the two-VM QEMU network lab (`scripts/qemu-net-lab.sh`), run by `make test`, covering DHCP, DNS, NAT, LAN-only SSH, and the WAN default-deny.
- Replace the Phase 1 profile contract test with `tests/phase2-profile.sh`.
- Add the pinned fwOS Phase 1 Archiso profile and BIOS/UEFI QEMU smoke tests.
