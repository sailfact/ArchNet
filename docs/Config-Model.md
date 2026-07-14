# fwOS Config Model (schema v1)

`/etc/project/config.yaml` is the single source of truth for runtime
configuration. It is validated against `config/schema.json` (JSON Schema
draft 2020-12, installed at `/usr/lib/fwos/schema.json`), then by semantic
cross-reference checks, before anything is rendered. The repository example
`config/example-config.yaml` encodes the default topology and is shipped as
the appliance's initial config.

## Field reference

| Section | Contents | Notes |
|---|---|---|
| `version` | Config model version | Must be `1`; migrations key off it. |
| `system.hostname` | Appliance hostname | Rendered to `/etc/hostname` (bare name, no banner — `hostnamectl` must be able to rewrite it identically), applied live via `hostnamectl set-hostname`, and used for the `<hostname>.<domain>` DNS record. |
| `interfaces.<name>` | `device` (e.g. `eth0`), `ipv4.mode` (`dhcp` or `static`), `ipv4.address` (CIDR, static only) | One IPv4 address per interface in the MVP. |
| `zones.<name>` | `interfaces: [..]` | Every interface belongs to exactly one zone. `firewall` is reserved for the appliance itself. Zone names become nftables identifiers (`<zone>_if`), so they allow underscores but not hyphens. |
| `rules[]` | `name`, `from`, `to`, `action` (`accept`/`drop`), optional `protocol` (`tcp`/`udp`/`icmp`), `dport` (port or `a-b`), `comment` | Ordered; evaluated on top of the implicit base policy. `to: firewall` targets the input chain, any other zone the forward chain. |
| `nat.masquerade[]` | `from`, `out` zones | Scoped to the source zone's static subnets when they are all known. |
| `dhcp.servers[]` | `interface`, `range.start/end`, `lease_time` | Interface must be static; range must sit inside its subnet and exclude the interface address. |
| `dns` | `domain`, `upstream` (`resolved` only for now), `local_records[]` (`name`, `address`) | `upstream` is an enum so an unbound/kea profile can be added without a model rewrite. |
| `users[]` | `name`, `role` (`admin`), `ssh_keys[]` | **Placeholder in Phase 3**: validated, not rendered. |
| `services.ssh` | `enabled`, `zones[]` | **Placeholder in Phase 3**: validated, informational; sshd config remains a static build input until hardening. |

## Implicit base firewall policy

The renderer always emits, regardless of the rules list:

- default-deny (`policy drop`) on the input and forward chains;
- `ct state invalid drop` and `ct state established,related accept`;
- loopback accept;
- DHCP client lease traffic (`udp sport 67 dport 68`) on every
  interface with `ipv4.mode: dhcp`.

A config document cannot express "allow unsolicited WAN ingress by
default"; that invariant lives in code, not in data.

## Semantic validation

Beyond the JSON Schema, the engine rejects: unknown interface/zone
references, an interface in zero or two zones, a zone named `firewall`,
duplicate devices or rule names, `from == to` rules, `dport` without
`tcp`/`udp`, inverted port ranges, DHCP servers on dhcp-mode interfaces,
DHCP ranges outside the interface subnet or containing the interface
address, static addresses that are network/broadcast addresses, and
invalid local-record IPs. Errors are structured (`code`, `message`,
JSON-pointer-style `path`) and surface verbatim in `fwctl --json`.

## The apply state machine

Every change runs `Validate -> Render -> Test -> Apply -> Confirm -> Commit`:

1. **Validate** — schema + semantic checks (`fwctl` exit 3 on failure).
2. **Render** — deterministic, timestamp-free output to a staging
   directory under `/run/project/staging/`.
3. **Test** — `nft -c -f` and `dnsmasq --test` against the staged files
   (exit 4 on failure). networkd has no offline checker; validation is
   the gate for `.network` units.
4. **Apply** — in hard order: unconditional pre-apply backup to
   `/var/lib/project/backups/<timestamp>/` (last 10 kept), pending state
   written, rollback timer armed via a `systemd-run` transient unit and
   verified active, and only then are files installed and services
   reloaded: `nft -f`, `networkctl reload` **plus** `networkctl
   reconfigure` of every managed link (reload alone only re-reads unit
   files and would leave the old addresses live until reboot),
   `hostnamectl set-hostname`, and finally `systemctl restart dnsmasq`.
   Any failure here restores the backup immediately.
5. **Confirm** — `fwctl confirm` within the window (default 120 s,
   `apply --timeout N`) cancels the timer; otherwise the timer runs
   `fwctl rollback --pending` and the previous state returns.
6. **Commit** — the live config becomes the committed baseline
   (`/var/lib/project/committed-config.yaml`), recorded in
   `/var/lib/project/history.log`.

Rollback (timer-fired or manual `fwctl rollback [--to ID]`) restores the
backup's config and rendered files, reloads services, and first saves the
discarded state as a `*-prerollback` backup for forensics (the restore
target is exempt from backup pruning so taking that snapshot can never
delete it). Rollback is
deliberately immediate and unconfirmed — it is the safety net, and arming
a timer for it would recurse.

The pre-apply backup pairs the rendered files with the *committed* config
rather than the live one, because the live file is edited in place before
`fwctl apply` runs; this is what lets rollback restore a config text that
matches the restored rendered state.

## Build-time rendering

`make stage` (run automatically by `make iso` and `make test`) copies the
engine to `airootfs/usr/lib/fwos/`, stages the example config as both the
live config and the committed baseline, and renders the default service
files into `airootfs/`. All staged output is gitignored: rendered files
are renderer output only, never committed, never hand-edited. On the
appliance the same renderer runs through `fwctl apply`.
