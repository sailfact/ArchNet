# fwOS Agent Rules

## 1. Project identity

fwOS is the working name for an Arch-based firewall/router appliance managed declaratively from one YAML configuration model. `fwctl` is its planned management CLI, and later API and Web UI clients must use the same model. It targets pfSense/OPNsense-category capability with a NixOS-like, file-first architecture. It is not a general-purpose Arch installation, a throwaway prototype, or a VyOS-style transactional imperative shell.

## 2. Non-negotiable invariants

- Treat rendered nftables rulesets, dnsmasq configurations, and systemd-networkd units as build output. Never hand-edit them, write them outside the renderer, or teach users to edit them; regenerate them from the validated config model.
- Treat `/etc/project/config.yaml` as the single source of truth for runtime configuration. Never create a second mutable configuration authority.
- Route every state change through `Validate -> Render -> Test -> Apply -> Confirm -> Commit`. Never skip or reorder a stage.
- Create a pre-apply backup before every apply. Never make backup optional.
- Arm the rollback timer before applying network or firewall state, then require confirmation before commit. Never permit an apply code path without both safeguards; admin lockout (R1) is this project's highest-severity failure mode.
- Make the Phase 8 API and Phase 9 Web UI mutate the config model only. Never let either write raw system files; this prevents the R4 config-model retrofit.
- Preserve default-deny unsolicited WAN ingress and LAN-only authenticated management by default.
- Keep `fwctl` independent of the Web UI and expose `--json` wherever the capability is automatable.
- Never perform blind full-system pacman upgrades. Pin or snapshot packages, test updates before Stable promotion, and preserve update rollback against Arch drift (R3).
- Gate phase completion and Stable promotion on the standard QEMU lab, including lockout and rollback coverage where relevant.
- Do not distribute externally until packages and releases are signed, reproducible, checksummed, and channel-gated.
- Keep build scripts, configuration schemas, PKGBUILDs, tests, and documentation in Git.

## 3. Repo layout

- `./` contains the current archiso profile and build-host inputs; never add rendered runtime state here.
- `.agents/` is empty, environment-owned agent metadata; never add product code here.
- `.codex/` is empty, environment-owned Codex metadata; never add product code here.
- `.git/` contains version-control metadata; never edit it directly.
- `.github/` contains CI workflows only; never put runtime logic there.
- `cli/` is currently empty; put `fwctl` code here after its language is decided, never core rendering logic or direct system-file writers.
- `config/` is currently empty; put the schema and source configuration examples here, never rendered service files.
- `core/` is currently empty; put the config model, renderers, and apply state machine here, never UI code.
- `scripts/` contains verified build and QEMU test helpers; never put core product behavior there.
- `tests/` contains the Phase 1 profile and QEMU checks; keep production configuration out.

## 4. The config model contract

- Keep the repository schema under `config/`; no schema file exists yet, so stop and obtain sign-off before choosing its filename.
- Parse YAML and pass JSON Schema validation before rendering. Treat validation as the gate, not an advisory check.
- Treat every schema change as a breaking change that cascades into `fwctl`, the API, and the Web UI. Obtain explicit sign-off before changing it.

## 5. Development loops

| Tier | Target time | Use it for | Current entrypoint |
|---|---:|---|---|
| netns | seconds | Rule behavior and config-render logic | Planned; no repository command exists yet |
| QEMU | about 1 minute | Real boot, UEFI, and init behavior | `make qemu` for interactive UEFI boot; `make test` gates BIOS and UEFI. |
| libvirt/LXD staging | minutes | End-to-end behavior with a real upstream | Planned; no repository command exists yet |

- Never substitute Docker for QEMU: containers share the host kernel and do not boot.
- Use Docker only as an Arch build host for mkarchiso on non-Arch machines.
- Develop config-engine and CLI changes on a plain Arch development box. Do not rebuild the ISO to test those changes; keep the fast software loop decoupled from the slow ISO loop.

## 6. Definition of Done

A phase is done only when every item passes:

- [ ] Feature works in the **QEMU test lab** against the standard topology.
- [ ] Automated tests cover the happy path **and** the lockout/rollback path where relevant.
- [ ] Changes flow through the config model + state machine (no out-of-band file edits).
- [ ] `fwctl` and (where applicable) `--json` reflect the new capability.
- [ ] Docs/changelog updated; PKGBUILD updated if it ships as a package.
- [ ] Safety nets intact: validation, pre-apply backup, rollback all still pass.

## 7. Scope discipline

- Limit the MVP to Phases 1-3 plus thin slices of Phase 4 (CLI), Phase 5 (installer), and Phase 6 (test lab).
- Keep Web UI, IDS/IPS, multi-WAN, IPsec, high availability, complex reporting, and package marketplaces out of the MVP.
- Treat a helpful out-of-scope implementation as harm under R2. Put new ideas in the project backlog file, not in code; if no backlog file exists, ask where to create it.

## 8. Unresolved decisions

Stop and ask before choosing any of these:

- Build the ISO locally or in cloud CI from day one.
- Implement `fwctl` in Python, Go, Rust, or another language.
- Keep dnsmasq only or later add an unbound/kea advanced backend.
- Keep the base mutable or move toward a semi-immutable design.

Do not turn a plan recommendation into a decision without explicit approval.

## 9. What to do when stuck

- Ask; never guess.
- Never fabricate a command, file path, package name, or capability.
- Verify commands in the current Makefile or scripts before citing them. Use only targets and scripts present in the current tree; mark all others as planned.
- Mark absent tooling as planned rather than presenting it as runnable.
