# Project Plan — Arch-Based Firewall/Router Distribution

> **Working title:** *fwOS* (placeholder — the roadmap uses `fwctl`, `/etc/project/config.yaml`, and `project-core`; rename throughout once a real name is chosen).
> **Plan owner:** _TBD_  ·  **Last updated:** _on creation_  ·  **Status:** Draft v0.1

---

## 1. Project Overview

Build a custom, declaratively-managed firewall/router operating system on top of Arch Linux — conceptually in the same category as pfSense/OPNsense, but Arch-based, config-file-driven, and CLI-first. The product ships as a bootable ISO with an installer, a single source-of-truth config model, a management CLI, and (later) an API + web UI, advanced networking, VPN, monitoring, and IDS/IPS.

The work is organized into **5 milestones / 20 phases**, with a tightly-scoped **MVP** carved out of Milestones 1–2 as the first public demo.

### Assumptions & constraints (adjust before committing dates)
- **Team:** 1–3 engineers with working Linux, networking (nftables/routing/DHCP/DNS), and packaging experience.
- **Goal:** a production-capable appliance, not a throwaway prototype — so safety nets (rollback, validation, backups) are first-class from the MVP.
- **Distribution base:** Arch rolling-release. This is a deliberate risk (see §7) — base packages move under you, so version pinning / snapshotting is a design concern, not an afterthought.
- **Estimates** are in **person-weeks (pw)** of focused work and assume the team isn't context-switching across other projects. Calendar time roughly = effort ÷ team size, plus overhead.

---

## 2. Scope

### In scope (eventually)
The full feature set across all 20 phases: custom ISO + installer, declarative config engine, CLI, API, web UI, VLANs/zones, advanced firewall features, advanced DNS/DHCP, WireGuard VPN, monitoring/logging, backup/restore, hardening, advanced routing/multi-WAN, optional Suricata IDS/IPS, and a formal release pipeline.

### Explicitly OUT of scope for the MVP
Per the roadmap, the first public demo deliberately excludes: **Web UI, IDS/IPS, multi-WAN, IPsec, high availability, complex reporting, and package marketplaces.** Guard this boundary aggressively — scope creep is the #1 schedule risk for a project this broad.

### MVP definition (the real first target)
A working prototype that proves the core thesis:
1. **Core OS** — custom Arch ISO (archiso) + installer to write it to disk.
2. **Networking** — WAN DHCP, LAN static IP, LAN DHCP, DNS forwarding.
3. **Security** — NAT, default-deny inbound, LAN-only SSH.
4. **Management** — basic CLI with config validation + rollback.
5. **Testing** — functional QEMU lab verifying boots and network flow.

> The MVP draws from **Phases 1, 2, 3** in full, plus a *thin slice* of **Phase 4 (CLI)**, **Phase 5 (installer)**, and **Phase 6 (test lab)**. It does **not** require those phases to be complete.

---

## 3. Objectives & Success Criteria

| # | Objective | Success criterion |
|---|-----------|-------------------|
| O1 | Boot a custom firewall OS from ISO | Boots cleanly in QEMU and on at least one physical/UEFI target |
| O2 | Route + protect a LAN | A LAN client gets DHCP, resolves DNS, reaches the WAN via NAT; unsolicited inbound WAN traffic is dropped |
| O3 | Make config safe to change | Every change is validated, backed up, and auto-rolls-back on lockout |
| O4 | Make the system operable | An admin can inspect and change state entirely from `fwctl`, with JSON output for automation |
| O5 | Make releases trustworthy | Signed packages, versioned channels, reproducible ISO builds, clear changelogs |

---

## 4. Milestones, Phases & Effort

Effort is a planning estimate for a competent small team. The **Config Engine (Phase 3)** is the spine of the system — treat its estimate as the one most worth getting right.

### Milestone 1 — The Core Engine (Phases 1–3) · ~6–9 pw
| Phase | Summary | Est. |
|-------|---------|------|
| **1. Base Arch Image** | archiso build; strip live/desktop packages; add core stack (nftables, systemd-networkd, systemd-resolved/dnsmasq, openssh, curl, jq, vim); enable services; hostname/MOTD/recovery shell; QEMU boot. | 1–2 pw |
| **2. Basic Firewall MVP** | Default topology (WAN DHCP; LAN 10.10.10.1/24, DHCP .100–.200); IPv4 forwarding; foundational nftables (drop inbound WAN, LAN→firewall, LAN→WAN, NAT, established); dnsmasq for DHCP+DNS. | 2–3 pw |
| **3. Declarative Config Engine** | `/etc/project/config.yaml` as source of truth (interfaces, zones, rules, NAT, DHCP, DNS, users, services); renderer for core services; schema validation; dry-run; **pre-apply backups + rollback timer**. | 3–4 pw |

### Milestone 2 — Management & Infrastructure (Phases 4–7) · ~11–15 pw
| Phase | Summary | Est. |
|-------|---------|------|
| **4. CLI Tool (`fwctl`)** | `status`, `interfaces`, `config validate`, `apply`, `backup/rollback`, `update`; `--json` output; state machine: Validate → Render → Test → Apply → Confirm → Commit. | 3–4 pw |
| **5. Installer** | UEFI install, disk wipe, root/admin setup, interface selection, WAN/LAN assignment; unattended install, first-boot wizard, rescue mode, factory reset. | 3–4 pw |
| **6. Test Lab** | Automated QEMU/libvirt topology (WAN VM · Firewall VM · LAN client); tests for boot, install, DHCP/DNS, NAT, block rules; netns for fast CI. | 2–3 pw |
| **7. Packaging & Updates** | Arch PKGBUILDs (`project-core`, `project-cli`, …); own pacman repo with Dev/Testing/Stable channels; signed packages; update rollback; block blind full-system upgrades. | 3–4 pw |

### Milestone 3 — UI & Network Expansion (Phases 8–11) · ~12–17 pw
| Phase | Summary | Est. |
|-------|---------|------|
| **8. API Backend** | LAN-bound, authenticated API (status, rules, NAT, DHCP, logs, backups). **Hard rule: API edits the config model only — never writes raw system files.** | 3–4 pw |
| **9. Web UI** | Dashboard for interfaces, rules, logs, backups; config preview + rollback warnings; CLI stays fully independent of the UI. | 4–5 pw |
| **10. VLANs & Zones** | Zone model (WAN/LAN/DMZ/MGMT/GUEST/VPN); trunk interfaces; inter-zone rules; per-VLAN DHCP/DNS/NAT. | 3–4 pw |
| **11. Firewall Features** | Aliases, rule groups, comments, ordering; port forwarding, 1:1 NAT, outbound NAT modes; rate limiting; bogon/private-WAN blocking. | 3–4 pw |

### Milestone 4 — Advanced Services (Phases 12–16) · ~15–21 pw
| Phase | Summary | Est. |
|-------|---------|------|
| **12. DNS Improvements** | Keep dnsmasq (simple profile); add advanced profile (unbound + kea-dhcp4); overrides, recursion, DNSSEC, blocklists, split DNS, query logging. | 3–4 pw |
| **13. DHCP Improvements** | Static reservations, live lease viewer, per-interface scopes, PXE, lease export, local DNS registration. | 2–3 pw |
| **14. VPN (WireGuard)** | Server tunnels, site-to-site, road-warrior; QR export; peer dashboard; per-peer firewall rules. (IPsec/OpenVPN deferred.) | 3–5 pw |
| **15. Monitoring & Logging** | Metrics dashboard (CPU/RAM/throughput/states/blocked events); centralized logs; remote syslog; Prometheus exporter. | 4–5 pw |
| **16. Backup & Restore** | Scheduled + encrypted + versioned backups; auto-backup before apply/update. | 2–3 pw |

### Milestone 5 — Enterprise Hardening & Release (Phases 17–20) · ~14–20 pw
| Phase | Summary | Est. |
|-------|---------|------|
| **17. Hardening** | Disable root SSH; admin/sudo model; firewall self-protection; read-only/semi-immutable base option; secure boot; brute-force protection. | 4–5 pw |
| **18. Advanced Routing** | Static + policy-based routing; multi-WAN (failover/load-balance); gateway monitoring; DynDNS; PPPoE. | 4–6 pw |
| **19. IDS/IPS & Filtering** | Optional Suricata (IDS first → IPS later); alert dashboards; safe defaults; perf warnings; blocklist feeds. | 4–5 pw |
| **20. Release Process** | Versioning (0.1 → 1.0); automated ISO build per release; checksums, signing, changelogs, migration scripts. | 2–4 pw |

**Total indicative effort:** ≈ **58–82 person-weeks** to a polished 1.0. With 2 engineers and realistic overhead, that's roughly **9–15 months**; solo, plan on materially longer.

---

## 5. Dependencies & Critical Path

The config engine is the load-bearing wall. Almost everything routes through it.

```
Phase 1 (Base ISO)
   └─> Phase 2 (Firewall base)
          └─> Phase 3 (Config Engine)  ◄── CRITICAL: spine of the system
                 ├─> Phase 4 (CLI)  ──────┐
                 ├─> Phase 5 (Installer)  │
                 ├─> Phase 8 (API) ─> Phase 9 (Web UI)
                 ├─> Phase 10 (Zones) ─> Phase 11 (FW features)
                 ├─> Phase 12/13 (DNS/DHCP)
                 ├─> Phase 14 (VPN)
                 └─> Phase 17 (Hardening)
   Phase 6 (Test Lab) ──┤ runs in parallel; gates everything via CI
   Phase 7 (Packaging) ─┘ needed before any external release
```

**Critical-path notes**
- **Phase 3 blocks the most downstream work.** Don't rush its schema design or rollback semantics — reworking the config model later cascades into the CLI, API, and UI.
- **Phase 6 (Test Lab) should start early and grow continuously.** It's listed in Milestone 2, but stand up a minimal version during the MVP so every change is verified against real boot + network flow.
- **Phase 8's "config-model-only" rule** is an architectural invariant: the API and UI must never touch raw system files directly. Designing Phase 3's model with this in mind avoids a painful retrofit.
- **Phase 7 (Packaging) gates external distribution.** Internal MVP demos can run from a manually built ISO; signed packages + channels are required before anyone else installs it.

---

## 6. Key Decisions (resolve early)

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **ISO build: local vs. cloud CI from day one** *(your open question)* | (a) Build locally in a container/VM; (b) GitHub Actions / CI pipeline immediately | **Build locally for the MVP**, scripted (`make iso`) and reproducible. Introduce CI ISO builds when packaging matures (Phase 7) and formalize in Phase 20. Reason: archiso iteration is faster and cheaper to debug locally; premature CI adds friction before the build is even stable. |
| **Config format/validation** | YAML + JSON Schema; YAML + custom validator; TOML | YAML (per roadmap) with a **schema** (JSON Schema or similar) so validation is declarative and reusable across CLI/API. |
| **DHCP/DNS engine** | dnsmasq only; dnsmasq (simple) + unbound/kea (advanced) | Ship dnsmasq for MVP; design config model so the advanced profile (Phase 12/13) is a swappable backend, not a rewrite. |
| **CLI language** | Python, Go, Rust, shell | Pick one with strong YAML/schema libs and easy static binaries for packaging. Go or Python are pragmatic; avoid heavy shell for the state machine. |
| **Immutable base** | Mutable now; semi-immutable later (Phase 17) | Keep mutable for MVP but avoid designs that *assume* mutability, so the Phase 17 option stays open. |

---

## 7. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | **Admin lockout** when applying firewall/network changes remotely | High | High | Rollback timer + confirm step in the state machine (Validate→…→Confirm→Commit); test in lab before every apply. *Already designed in — keep it sacrosanct.* |
| R2 | **Scope creep** across 20 phases delays the MVP indefinitely | High | High | Freeze MVP scope (§2); defer all "Strictly Avoid" items; track new ideas in a backlog, not the current milestone. |
| R3 | **Arch rolling-release drift** breaks the appliance unpredictably | Medium | High | Pin/snapshot package versions; gate upgrades (Phase 7 "no blind full-system upgrades"); test channel before Stable. |
| R4 | **Config-model retrofit** if API/UI bypass the model | Medium | High | Enforce the "model-only" invariant from Phase 3; code-review for any direct file writes. |
| R5 | **Insufficient network test coverage** ships subtly broken routing | Medium | High | Invest in Phase 6 early; automate DHCP/DNS/NAT/block-rule tests in CI; use netns for speed. |
| R6 | **Signing-key / supply-chain compromise** in the package repo | Low | High | Hardware-backed or well-isolated signing keys; reproducible builds; published checksums (Phase 20). |
| R7 | **Single-maintainer bus factor** | Medium | Medium | Documentation as you go; PKGBUILDs + scripts in version control; avoid undocumented tribal knowledge. |
| R8 | **Appliance self-compromise** (the firewall itself is attacked) | Medium | High | Phase 17 hardening (no root SSH, sudo model, self-protection rules, brute-force protection); LAN-only management surfaces by default. |

---

## 8. Definition of Done (per phase)

A phase is "done" only when **all** of the following hold:
1. Feature works in the **QEMU test lab** against the standard topology.
2. Automated tests cover the happy path **and** the lockout/rollback path where relevant.
3. Changes flow through the config model + state machine (no out-of-band file edits).
4. `fwctl` and (where applicable) `--json` reflect the new capability.
5. Docs/changelog updated; PKGBUILD updated if it ships as a package.
6. Safety nets intact: validation, pre-apply backup, rollback all still pass.

---

## 9. Indicative Timeline (2-engineer team)

> Calendar estimate; compress with more engineers, expand if solo or part-time.

| Quarter | Focus | Exit gate |
|---------|-------|-----------|
| **Q1** | Milestone 1 + MVP slice of Phases 4–6 | **🎯 MVP public demo:** boots, routes, NAT, DHCP/DNS, validated config with rollback, QEMU verified |
| **Q2** | Finish Milestone 2 (full CLI, installer, test lab, packaging) | Installable build from signed packages; CI green |
| **Q3** | Milestone 3 (API, Web UI, zones, firewall features) | Web-managed multi-zone firewall; CLI still standalone |
| **Q4** | Milestone 4 (advanced DNS/DHCP, WireGuard, monitoring, backups) | VPN + observability + disaster recovery |
| **Q5** | Milestone 5 (hardening, advanced routing, IDS/IPS, release process) | **🎯 1.0:** hardened, multi-WAN, optional Suricata, automated signed release |

---

## 10. Governance & Working Practices
- **Source of truth in git** from day one (ISO build scripts, config schema, PKGBUILDs, tests, docs).
- **Three release channels** (Dev → Testing → Stable) once Phase 7 lands; nothing reaches Stable without passing the test lab.
- **Every change is a config-model change**, exercised through Validate → Render → Test → Apply → Confirm → Commit.
- **Backlog discipline:** anything outside the current milestone goes to a backlog, reviewed at milestone boundaries — not mid-flight.
- **Decision log:** record the §6 decisions and any later reversals so the rationale survives.

---

## 11. Immediate Next Actions (to kick off Milestone 1)
1. Decide the §6 build question (recommend **local archiso build**, scripted + reproducible).
2. Set up the git repo with `iso/`, `config/` (schema + sample `config.yaml`), `pkg/` (PKGBUILDs), `tests/`.
3. Build the Phase 1 ISO and confirm a clean QEMU boot (Objective O1).
4. Stand up a **minimal** QEMU topology (one WAN VM, firewall, one LAN client) now — don't wait for Phase 6.
5. Draft the Phase 3 `config.yaml` schema early, even before the renderer — it shapes everything downstream.