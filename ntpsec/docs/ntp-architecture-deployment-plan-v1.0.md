# Dual-stack NTP architecture and deployment

## Implementation status

| Field | Value |
| --- | --- |
| Plan version | `1.0` |
| Phase | Repository foundation complete; read-only baseline collector definition is next |
| Last updated | `2026-08-10` |
| Current accepted live state | Existing dual-node NTP service; no live state inspected or changed under this plan |
| Current repository state | Condensed governance policy and foundation files accepted by repository validation; deployable NTPsec artifacts remain pending live capture |
| Current next single gate | Define and review a read-only baseline collector for `j1-svntp1`; do not execute it without separate authorization |
| Authorization boundary | This document authorizes repository planning only. It does not authorize SSH, UniFi access, file installation, network changes, service actions, DNS reloads, or tests that alter live state |

## Purpose

This document governs the audit and deployment of the two Raspberry Pi NTPsec
servers on the Default LAN. It records design decisions, action boundaries,
validation, rollback, and evidence. Update it after each defined or executed
gate so another operator can resume from the status table without reconstructing
state from chat or shell history.

The project covers:

- Four-week leapfile maintenance with `ntpleapfetch` and systemd.
- Static dual-stack host networking and DHCP-resistant DNS settings.
- Exact mirrors and audits of each live `/etc/ntp.conf`.
- Local-zone A, AAAA, SRV, and PTR records.
- UniFi DHCP, IPv4 and IPv6 firewall policy, and active/standby DNAT.
- NTP host and service inventory.

## Architecture

### Network

| Item | Value |
| --- | --- |
| UniFi network | `Default LAN` on VLAN 1 |
| IPv4 subnet | `10.1.0.0/22` |
| IPv6 ULA subnet | `fd36:5aa8:6971:1::/64` |
| IPv4 gateway | `10.1.0.1` |
| IPv4 DNS VIP | `10.1.0.55` |
| IPv6 DNS VIP | `fd36:5aa8:6971:1::55` |
| DHCP NTP servers | `10.1.0.50`, `10.1.0.51` |

UniFi DHCP Option 42 supplies both IPv4 NTP servers. UniFi blocks outbound UDP
123 from other Default LAN clients and redirects hard-coded external NTP
destinations to the active local DNAT target.

### Servers

| Property | `j1-svntp` | `j1-svntp1` |
| --- | --- | --- |
| Service name | `ntp.local.theama.co` | `ntp1.local.theama.co` |
| IPv4 | `10.1.0.50/22` | `10.1.0.51/22` |
| Permanent ULA | `fd36:5aa8:6971:1::50/64` | `fd36:5aa8:6971:1::51/64` |
| Platform | Raspberry Pi 4B, 8 GB | Raspberry Pi 4B, 4 GB |
| GPS | Uputronics GPS/RTC expansion board | Uputronics GPS/RTC expansion board |
| Power | Raspberry Pi PoE+ HAT | Raspberry Pi PoE+ HAT |
| OS | Debian 11 | Debian 11 |
| NTPsec | `1.2.1+82-g7abe7fba6` | `1.2.1+82-g7abe7fba6` |
| Rollout order | Second | First |

Both nodes act as independent authoritative time sources. The project will not
add Keepalived, VRRP, or another NTP HA layer.

## Locked decisions

### Addressing

- `j1-svntp` uses `fd36:5aa8:6971:1::50/64`.
- `j1-svntp1` uses `fd36:5aa8:6971:1::51/64`.
- Both nodes use `10.1.0.55` and `fd36:5aa8:6971:1::55` for DNS.
- Host profiles reject DNS values learned through DHCP or Router
  Advertisement.
- Host profiles retain router-advertised global IPv6 addresses and the IPv6
  default route.

### DNS service discovery

Publish equal-priority and equal-weight records:

```dns
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp.local.theama.co.
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp1.local.theama.co.
```

Each SRV target must have matching A and AAAA records. Each physical address
must have one canonical PTR that points to its service name.

### DNAT

Maintain four DNAT rules:

| Family | Target | State |
| --- | --- | --- |
| IPv4 | `10.1.0.50` | Active |
| IPv4 | `10.1.0.51` | Disabled standby |
| IPv6 | `fd36:5aa8:6971:1::50` | Active |
| IPv6 | `fd36:5aa8:6971:1::51` | Disabled standby |

Do not enable both rules in one family. The project uses a manual DNAT
failover runbook and does not add NTP HA.

### Leapfile maintenance

Both nodes have working Internet access and can run the current
`ntpleapfetch` command. Preserve that egress behavior. Add a schedule through a
oneshot service and timer:

```ini
OnBootSec=15min
OnUnitActiveSec=4w
RandomizedDelaySec=30min
```

The initial live audit must confirm the executable path, options, source URL,
leapfile path, owner, group, mode, retry behavior, and installed NTPsec reload
behavior. Do not add an `ntpd` restart without evidence that this build needs
one.

## Repository ownership

| Information | Source of truth |
| --- | --- |
| NTPsec and client configuration | `homelab-ntp` |
| This governing plan | `homelab-ntp/ntpsec/docs` |
| Host membership, functions, components, and OS facts | `homelab-server-configs/inventory` |
| A, AAAA, PTR, and SRV records | `homelab-dns` |
| Addresses, DHCP, firewall policy, and DNAT | `homelab-network` |
| Architecture diagrams | `homelab-docs` |
| Secrets and private keys | Approved secrets manager |

## Planned repository layout

```text
ntpsec/
├── configs/
│   ├── j1-svntp/
│   │   └── ntp.conf
│   └── j1-svntp1/
│       └── ntp.conf
├── docs/
│   ├── ntp-architecture-deployment-plan-v1.0.md
│   └── dual-node-deployment-runbook.md
├── scripts/
│   ├── inspect-node.sh
│   ├── install-node-config.sh
│   └── validate-node.sh
├── templates/
│   ├── ntpleapfetch.service
│   └── ntpleapfetch.timer
└── tests/
    └── run.sh
```

Create deployable files after the read-only captures establish their exact
paths and contracts. Do not create guessed `ntp.conf` files or systemd units.

## Current repository evidence

The repository audit on `2026-08-10` found:

- `homelab-ntp` contains skeletal `client/` and `ntpsec/` trees.
- No deployable NTPsec configuration or service unit exists in the repository.
- `homelab-dns` already has IPv4 A and PTR data for `.50` and `.51` in its
  private ignored Unbound local-zone fragment.
- The local zone lacks the agreed NTP AAAA, IPv6 PTR, and SRV records.
- Pi-hole already forwards the ULA `/64` reverse namespace to Unbound.
- `homelab-server-configs` inventory has no NTP group or NTP hosts.
- `homelab-network` records the Default LAN ULA and DNS VIP design but has no
  NTP-specific firewall and DNAT runbook.
- All four repositories had clean `main` worktrees before this foundation
  change.

## Change-control model

Repository changes and local validation do not require live authorization. A
scoped approval may cover one complete read-only collection on one target. A
persistent deployment approval may include its defined preflight, mutation,
acceptance, and rollback checks.

### Gate requirements

Each persistent live action must define:

- Scope and host or controller target.
- Exact privileged script or command-bundle path and SHA-256.
- Preconditions and expected observations.
- Commands and permitted side effects.
- Evidence paths and sensitive-output handling.
- Success and rejection conditions.
- Cleanup and rollback.
- The next action that remains unauthorized.

Execution consumes the approved privileged mutation artifact. An edit, retry,
or scope change requires a new hash and authorization. Unexecuted repository
files use the normal edit and review workflow.

### Evidence rules

- Capture SSH stdout and stderr in separate protected local files.
- Record command and SSH status without collapsing them into one value.
- Give fail-closed acceptance conditions distinct labels.
- Retain ordinary diagnostic output. Redact secrets and protect output that may
  contain credentials or private material.
- Compare pre-state and post-state hashes for read-only actions.
- Inspect cleanup and persistent state after an interrupted action.

## Work plan

### Phase 0: repository foundation

Status: Complete.

1. Replace the generic `AGENTS.md` with NTP-specific repository and live-action
   rules.
2. Create this governing plan under `ntpsec/docs`.
3. Link the governing plan and architecture summary from the repository
   `README.md`.
4. Run Markdown, whitespace, secret, and pre-commit validation.
5. Record validation, artifact hashes, deviations, and the exact resume point.

Phase 0 makes no live-system or controller contact.

### Phase 1: define and execute read-only baselines

Status: Pending separate authorization.

Create a fail-closed collector, then run it against `j1-svntp1` before
`j1-svntp`. Capture:

- Host identity, Debian release, boot time, and package/build provenance.
- Active network manager, interface, connection profile, addresses, routes,
  DNS sources, and `/etc/resolv.conf` ownership.
- `/etc/ntp.conf`, defaults, drop-ins, startup options, ownership, modes, and
  SHA-256 values.
- NTPsec unit type, state, PID, restart count, listeners, and recent journal.
- GPSD state, serial device, PPS device, SHM units, and refclock observations.
- `ntpq` peers, reach, selection, stratum, leap state, offset, and jitter.
- Leapfile path, validity, expiration, ownership, mode, and hash.
- Current `ntpleapfetch` command, source URL, manual success, and exit status.
- Competing time daemons, local firewall state, and UDP 123 ownership.

Create a separate read-only UniFi audit for DHCP Option 42, address objects,
zone membership, firewall rule order, IP-family selectors, counters, and all
four planned DNAT rules. Export or capture enough state for exact rollback.

Acceptance requires complete evidence with no mutation and identical pre-state
and post-state hashes for protected host artifacts.

### Phase 2: build and validate repository candidates

Status: Blocked by Phase 1 evidence.

1. Mirror each live `/etc/ntp.conf` byte for byte in its host-specific path.
2. Audit the mirrors for GPS, PPS, upstream sources, NTS, restrictions,
   interfaces, IPv6, driftfile, statistics, and leapfile directives.
3. Create the `ntpleapfetch` service and four-week timer from installed command
   evidence.
4. Create node inspection, installation, rollback, and acceptance scripts.
5. Add success and rejection fixtures for parsers, fail-closed validators, and
   mutation scripts. Give simple collectors a focused dry run or self-test.
6. Validate shell, systemd, Markdown, YAML, secret scanning, and the complete
   repository suite.

Repository tests provide artifact evidence. Debian 11 and NTPsec checks on the
target remain required before deployment.

### Phase 3: configure and accept `j1-svntp1`

Status: Pending Phase 2 and separate authorization.

1. Reconfirm hostname, active profile, IPv4 state, NTP health, and rollback
   profile.
2. Check `fd36:5aa8:6971:1::51` for neighbor ownership and Duplicate Address
   Detection conflicts.
3. Preserve `10.1.0.51/22`, gateway `10.1.0.1`, Router Advertisement routes,
   and global IPv6 addressing.
4. Add the permanent ULA and both DNS VIPs. Disable automatic DNS replacement
   for IPv4 and IPv6.
5. Reactivate the profile from an access path that tolerates SSH interruption.
6. Validate addresses, lifetimes, routes, source selection, DNS, IPv4 and IPv6
   Internet access, and reboot persistence.
7. Install and validate the mirrored `ntp.conf` and leapfile units.
8. Confirm GPS/PPS selection and NTP service over IPv4 and IPv6.
9. Observe the node before authorizing primary work.

Rollback activates the captured pre-change profile and restores each accepted
configuration by exact hash. Inspect NTP health after rollback.

### Phase 4: configure and accept `j1-svntp`

Status: Pending accepted Phase 3 and separate authorization.

Repeat the Phase 3 controls with `10.1.0.50` and
`fd36:5aa8:6971:1::50`. Confirm `j1-svntp1` serves clients before the primary
network action and remains healthy throughout it.

Do not combine the two node changes. Re-run the primary preflight because the
secondary result does not prove the primary's profile, paths, or state.

### Phase 5: deploy local-zone DNS records

Status: Pending accepted dual-stack listeners on both NTP nodes.

Add and audit:

```dns
ntp.local.theama.co. IN A 10.1.0.50
ntp.local.theama.co. IN AAAA fd36:5aa8:6971:1::50
ntp1.local.theama.co. IN A 10.1.0.51
ntp1.local.theama.co. IN AAAA fd36:5aa8:6971:1::51
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp.local.theama.co.
_ntp._udp.local.theama.co. 180 IN SRV 0 50 123 ntp1.local.theama.co.
```

Retain the existing IPv4 PTR records and add:

```dns
fd36:5aa8:6971:1::50 PTR ntp.local.theama.co.
fd36:5aa8:6971:1::51 PTR ntp1.local.theama.co.
```

Reject duplicates and incomplete forward/reverse pairs. Validate the candidate
with the target `unbound-checkconf`. Install and query the standby DNS node,
exercise DNS failover, then install the primary DNS node. Query A, AAAA, SRV,
IPv4 PTR, and IPv6 PTR from both nodes and both DNS VIPs.

### Phase 6: audit and enforce UniFi policy

Status: Pending dual-stack node and DNS acceptance.

1. Reconcile DHCP Option 42 with `10.1.0.50` and `10.1.0.51`.
2. Place NTP-server allow policy above the Default LAN deny policy.
3. Allow both NTP devices to External over IPv4 and IPv6 UDP 123 and TCP 4460.
4. Deny other Default LAN clients access to External UDP 123 over both
   families.
5. Preserve the working `ntpleapfetch` download path.
6. Reconcile active and disabled standby DNAT rules with the locked table.
7. Validate rule counters, connection state, return traffic, and unrelated
   traffic.

For IPv6 External traffic, match a verified device object or the source address
observed on the wire. A rule that matches only the ULA may miss packets sourced
from the router-advertised global address.

Test DNAT from a controlled VLAN 1 client with a hard-coded external
destination. Pair the client observation with UniFi counters and a capture on
the selected NTP node. Test standby promotion and restoration for one family
at a time. Leave the primary target active after acceptance.

### Phase 7: add inventory

Status: Pending accepted service state.

In `homelab-server-configs/inventory/prod`:

1. Add group `ntp` and `groups/ntp.yaml`.
2. Record function `ntp` and components `ntpsec` and `gpsd`.
3. Add host keys `j1-svntp` and `j1-svntp1` with their management FQDNs.
4. Add host files for display name, Raspberry Pi model and RAM, GPS/RTC HAT,
   PoE+ HAT, Debian release, and manual DNAT role.
5. Keep IP allocation and authoritative DNS records out of inventory.
6. Run strict YAML and inventory repository validation.

### Phase 8: end-to-end acceptance

Status: Pending Phases 3 through 7.

Acceptance requires:

- Both hosts retain their static IPv4 and permanent ULA after reboot.
- Both hosts retain global IPv6 and a Router Advertisement default route.
- Each resolver view contains only the two DNS VIPs for its address family.
- DHCP and Router Advertisement updates do not replace host DNS settings.
- GPS, PPS, and external sanity sources report the accepted selection and
  reach state on both nodes.
- NTP clients receive time over each node's IPv4 and IPv6 address.
- Each leapfile validates, and each timer reports a four-week next trigger.
- Both DNS nodes and both DNS VIPs return the agreed A, AAAA, PTR, and SRV data.
- Both NTP nodes reach approved IPv4 and IPv6 upstreams over UDP 123 and TCP
  4460.
- Other Default LAN clients cannot send UDP 123 to the External zone.
- Active IPv4 and IPv6 DNAT reach `j1-svntp`; the disabled standby rules can be
  promoted one family at a time to `j1-svntp1` and restored.
- Inventory names, functions, components, hardware, and OS facts match live
  observations.
- Each repository passes its focused tests, full baseline, secret scan, and
  whitespace checks.

Run an observation interval after the last change. Review offsets, jitter,
reach, leap state, systemd failures, DNS errors, and UniFi counters before
declaring acceptance.

## Rollback policy

- Roll back one node or one controller policy surface at a time.
- Keep the other NTP node serving throughout host rollback.
- Restore host files and NetworkManager profiles by accepted path and hash.
- Restore DNS on the node changed last, validate it, then decide whether the
  other DNS node needs rollback.
- Disable the promoted standby DNAT rule before restoring the primary rule for
  that family. Verify that one rule remains enabled.
- Restore UniFi objects and rule order from the pre-change export.
- After rollback, run a new read-only acceptance action. A successful rollback
  command does not prove restored service.

## Risks and controls

| Risk | Control |
| --- | --- |
| SSH loss during profile activation | Use console or an access path that tolerates interruption; verify a rollback profile before activation |
| Duplicate ULA | Check neighbor ownership and Duplicate Address Detection before acceptance |
| Loss of global IPv6 | Keep `ipv6.method auto`, Router Advertisement routes, and source-selection checks |
| DHCP replaces host DNS | Set and validate automatic-DNS ignore flags for both families |
| NTPsec accepts config but loses PPS | Check refclock variables, peer selection, reach, and journal after deployment |
| Leapfile timer disrupts service | Confirm installed reload behavior and omit restart unless required |
| Firewall allow does not match IPv6 source | Match a verified device object or observed global source and inspect counters |
| Both DNAT rules become active | Validate enabled-state cardinality before and after each controller action |
| DNS records precede listeners | Deploy records after both nodes serve NTP on their permanent addresses |
| Repository validation overstates live acceptance | Require target-node and client evidence for each runtime claim |

## Deviation log

| ID | Date | Deviation | Rationale | Status |
| --- | --- | --- | --- | --- |
| None | 2026-08-10 | No deviations recorded | The plan matches the approved preplanning decisions | N/A |

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

## Exact resume point

Define a read-only `j1-svntp1` baseline collector with an exact output contract,
focused self-test, and SHA-256. Stop before execution and request one scoped
authorization for that complete read-only node collection. No host or UniFi
contact has been authorized.
