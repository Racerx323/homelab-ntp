# NTPsec implementation history

The [governing architecture](docs/ntp-architecture-deployment-plan-v1.0.md)
defines the approved design and acceptance criteria. This file records
repository observations, operation outcomes, deviations, and the next gate.
A plan entry or history entry does not authorize live action.

## Current status

| Field | Value |
| --- | --- |
| Phase | Raspberry Pi OS Lite (64-bit), Trixie clean-rebuild planning; read-only baseline definition is next |
| Last updated | `2026-09-16` |
| Reported live state | Existing dual-node NTP service; no live state inspected or accepted under this plan |
| Current repository state | Trixie rebuild plan recorded; deployable artifacts and complete inventory facts remain pending live capture |
| Current next single gate | Define and review a read-only baseline collector for `j1-svntp1`; do not execute it without separate authorization |
| Authorization boundary | Repository planning only. No SSH, UniFi access, imaging, host rebuild, file installation, network or service change, DNS reload, or live-state test authorized |

## Repository observations

The repository audit on `2026-08-10` found skeletal `client/` and
`ntpsec/` trees, no deployable NTPsec configuration or service unit, and no
NTP host group in `homelab-server-configs` inventory. The private ignored
Unbound local-zone fragment had IPv4 A and PTR data for both nodes but lacked
the agreed NTP AAAA, IPv6 PTR, and SRV records. Pi-hole forwarded the ULA
reverse namespace to Unbound. `homelab-network` recorded the Default LAN
ULA and DNS VIP design but had no NTP-specific firewall and DNAT runbook.
All four repositories had clean `main` worktrees before the foundation change.

The inventory inspection on `2026-09-16` found no NTP group or hosts in
`prod/hosts.yaml`. `prod/groups/all.yaml` declared `needrestart` and
`watchdog` as common configuration and a Mailrise SMTP endpoint. Existing
host files showed a structured hardware, storage, management, and no-HA
schema. These are repository observations, not live node facts. Re-audit DNS
and UniFi before editing them.

## Deviation log

| ID | Date | Deviation | Rationale | Status |
| --- | --- | --- | --- | --- |
| None | 2026-08-10 | No deviations recorded | The plan matches the approved preplanning decisions | N/A |
| OS-001 | 2026-09-16 | Insert clean OS rebuild before dual-stack, DNS, and final UniFi policy work | User requested a Trixie rebuild and a full baseline, one node at a time | Approved design; no live action |

Add deviations before implementing work that differs from a locked decision or
accepted phase. Record the operator decision, affected artifacts, validation,
rollback impact, and replacement resume point.

## Implementation journal

### 2026-08-10: preplanning decisions

- Locked permanent ULAs `::50/64` and `::51/64`.
- Accepted equal-priority, equal-weight `_ntp._udp` SRV records.
- Selected one active and one disabled standby DNAT rule per IP family.
- Kept NTP without an HA mechanism.
- Confirmed both nodes have working Internet access and a working manual
  `ntpleapfetch` download path.
- Limited leapfile scope to a systemd four-week schedule and its validation.

### 2026-08-10: repository foundation

- Replaced the generic agent guidance with NTP-specific repository and
  live-infrastructure rules.
- Created this governing plan and linked it from the repository README.
- Made no SSH, DNS-node, NTP-node, or UniFi connection.
- Made no live configuration, service, firewall, DHCP, NAT, or DNS change.
- `git diff --check` passed.
- Markdownlint passed for `README.md` and this governing plan.
- `pre-commit run --all-files` passed ShellCheck, shfmt, Markdownlint, yamllint,
  actionlint, JSON validation, and Gitleaks. Hooks without matching files
  reported `Skipped`.
- `gitleaks detect --source . --no-git --redact --no-banner` scanned the full
  working tree, including untracked files, and found no leaks.
- `AGENTS.md` SHA-256:
  `ce27f170479d9bf39c25633bcd885bd8bff0370ca4c8fb1b396249277076a225`.
- `README.md` SHA-256:
  `68e3d59b87d07917a999f164887cc5f021f408f8bf4c75b6d7632d35da69f000`.
- The final handoff records this plan's SHA-256 because a document cannot
  contain its own stable digest.

### 2026-08-10: governance policy simplification

- Audited `AGENTS.md` and accepted all recommendations from that review.
- Reduced `AGENTS.md` from 229 to 130 lines.
- Removed duplicated architecture values and deployment procedure. The
  governing plan retains those details.
- Removed the unavailable `verify_done` requirement.
- Allowed one scoped approval to cover one complete read-only collection.
- Allowed a persistent deployment approval to include its defined preflight,
  acceptance, and rollback checks.
- Limited immutable artifact hashes to privileged remote scripts and
  preapproved command bundles.
- Limited the Caddy-derived SSH evidence and fail-closed assertion controls to
  privileged remote runners.
- Replaced mandatory regression fixtures for simple collectors with a focused
  dry run or self-test.
- `git diff --check`, focused Markdownlint, the full pre-commit suite, and the
  full working-tree Gitleaks scan passed after the policy change.
- Reviewed the Markdownlint-excluded `AGENTS.md` for stale requirements and
  writing defects.
- Updated `AGENTS.md` SHA-256:
  `b8155034057c4189c0c2c240098b2c7e5c3fe8bd4d668eb89d352fca82c22e96`.
- Made no live-system or controller contact.

### 2026-08-10: README current-state expansion

- Expanded the repository entry point with server hardware and software facts,
  the reported current network behavior, and the approved target changes.
- Added the current tracked layout and explained the placeholder `gitkeep`
  files.
- Added project status, cross-repository ownership, validation boundaries, and
  upstream hardware and implementation references.
- Distinguished reported live behavior from target design and repository-only
  validation.
- Updated `README.md` SHA-256:
  `de0227e797a4accf6bcbdb9e788fa6d9c85299390f6db1c30a822be6e2641d7a`.
- `git diff --check`, focused Markdownlint, the full pre-commit suite, and the
  full working-tree Gitleaks scan passed.
- Made no live-system or controller contact.

### 2026-09-16: Trixie rebuild planning

- Selected Raspberry Pi OS Lite (64-bit), Trixie, in Raspberry Pi Imager as the
  target for both Raspberry Pi 4B nodes. It is based on Debian 13 and is not
  pure Debian. The Debian 11 installations remain on their original SD cards;
  new spare cards will be used for both rebuilds.
- Added one-node-at-a-time clean-rebuild gates, full baseline-app and HAT
  validation, per-host recovery, and complete observed inventory specifications.
- `j1-svntp1` remains first; `j1-svntp` remains second. No live host,
  controller, DNS, or boot-media action was taken in this planning update.
- `git diff --check` and `pre-commit run --all-files` passed after the plan,
  README, and repository guidance changes. The cross-file verifier returned
  `not a git repository` from its own context and supplied no checks; it is
  not counted as verification. The CodeRabbit upload-based review was blocked
  by the workspace approval policy, so only local review was completed.

### 2026-09-16: deployment policy and history split

- Kept one-node-at-a-time rollout and separate authorization for each live node
  or controller stage. One approval may cover a hash-bound bundle from
  preflight through rollback.
- Made CodeRabbit optional and narrowed documentation-only validation to
  focused checks.
- Moved current status, repository observations, deviations, dated outcomes,
  and the resume point out of the governing architecture document into this
  file. No live host or controller action occurred in this repository edit.

### 2026-09-16: pre-commit audit integration

- Kept the shared scaffold hooks and documented a full working-tree Gitleaks
  scan for unstaged and untracked artifacts.
- Set the first NTP executable as the trigger for focused offline regression
  tests, a path-triggered pre-commit hook, and matching CI coverage.
- Retained fixed-flag shfmt checks; deferred a scoped write helper until shell
  scripts warrant one. No live host or controller action occurred.

### 2026-09-16: Munin endpoint requirement

- Added a `munin-node` endpoint to each NTP node's planned Trixie baseline,
  acceptance checks, and inventory components. The
  `homelab-monitoring-observability/Munin` component governs endpoint
  configuration and plugins; the approved poller and address families remain
  to be established from that component and read-only node evidence.
- The existing Caddy-specific Munin files belong to deferred Caddy deployment
  work. They do not establish live Munin service or an NTP endpoint template.
- No NTP node, Munin poller, or controller was contacted or changed.

## Exact resume point

Define a read-only `j1-svntp1` baseline collector with an exact output contract,
focused self-test, and SHA-256, including boot media, both HATs, all baseline
apps (including `munin-node`), and observed inventory facts. Stop before
execution and request one scoped authorization for that complete read-only
node collection. No host, UniFi, or boot-media contact has been authorized.
