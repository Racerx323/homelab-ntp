# homelab-ntp

Configuration, deployment tooling, and operating documentation for the homelab
NTPsec servers and clients.

> [!NOTE]
> The repository does not contain deployable `ntp.conf` files or systemd units
> yet. The [governing plan](ntpsec/docs/ntp-architecture-deployment-plan-v1.0.md)
> defines the design and acceptance criteria. [NTPsec history](ntpsec/HISTORY.md)
> records current status and the exact resume point.

## NTP servers

| Property | `j1-svntp` | `j1-svntp1` |
| --- | --- | --- |
| Service name | `ntp.local.theama.co` | `ntp1.local.theama.co` |
| IPv4 | `10.1.0.50/22` | `10.1.0.51/22` |
| Permanent ULA | `fd36:5aa8:6971:1::50/64` | `fd36:5aa8:6971:1::51/64` |
| Platform | Raspberry Pi 4B, 8 GB | Raspberry Pi 4B, 4 GB |
| GPS | Uputronics GPS/RTC expansion board | Uputronics GPS/RTC expansion board |
| Power | HAT model pending per-node confirmation | Working Raspberry Pi PoE HAT (2018), retained |
| Reported current OS | Debian 11 | Debian 11 |
| Rebuild target | Raspberry Pi OS Lite (64-bit), Trixie (Debian 13-based) | Raspberry Pi OS Lite (64-bit), Trixie (Debian 13-based) |
| Reported current NTPsec | `1.2.1+82-g7abe7fba6` | `1.2.1+82-g7abe7fba6` |
| Rollout order | Second | First |

The nodes provide independent time service. The design does not use
Keepalived, VRRP, or another NTP HA mechanism. Both nodes share a GPS Source
L1G1A-STD antenna through a two-output Uputronics splitter; j1-svntp supplies
antenna power. Its outage requires the governing plan's power-continuity gate.
Retain j1-svntp1's working PoE HAT; PoE+ is the selected replacement upon failure,
subject to separate compatibility validation and live authorization.

## Network model

| Item | Value |
| --- | --- |
| UniFi network | `Default LAN`, VLAN 1 |
| IPv4 subnet | `10.1.0.0/22` |
| IPv6 ULA subnet | `fd36:5aa8:6971:1::/64` |
| IPv4 gateway | `10.1.0.1` |
| IPv4 DNS VIP | `10.1.0.55` |
| IPv6 DNS VIP | `fd36:5aa8:6971:1::55` |
| DHCP NTP servers | `10.1.0.50`, `10.1.0.51` |

UniFi DHCP Option 42 supplies both IPv4 NTP servers. The reported current
firewall permits the NTP nodes to reach the External zone and blocks other
Default LAN clients from sending external UDP 123 traffic. An IPv4 DNAT rule
redirects hard-coded external NTP destinations to `j1-svntp`.

The approved target adds:

- Permanent ULA addresses on both nodes while retaining global IPv6 and Router
  Advertisement routes.
- Static DNS VIPs that DHCP and Router Advertisement cannot replace.
- IPv4 and IPv6 firewall-policy parity for UDP 123 and TCP 4460.
- One active and one disabled standby DNAT rule for each IP family.
- Equal-priority `_ntp._udp.local.theama.co` SRV records.
- A local leapfile maintained by `ntpleapfetch` every four weeks.
- A clean, one-node-at-a-time Trixie rebuild with Webmin, needrestart, msmtp,
  watchdog, a Munin endpoint, NTPsec, GPS/RTC/PPS, and installed PoE HAT acceptance.
  Spare SD cards will preserve both Debian 11 installations for rollback.

## Project status

Raspberry Pi OS Lite (64-bit), Trixie, is the locked rebuild image. No live
host or controller action has been authorized under this plan. See
[NTPsec history](ntpsec/HISTORY.md) for current state, completed work, and the
next gate.

## Current repository layout

```text
homelab-ntp/
├── client/
│   ├── configs/
│   │   └── gitkeep
│   ├── scripts/
│   │   └── gitkeep
│   └── templates/
│       └── gitkeep
├── ntpsec/
│   ├── HISTORY.md
│   ├── configs/
│   │   └── gitkeep
│   ├── docs/
│   │   └── ntp-architecture-deployment-plan-v1.0.md
│   ├── scripts/
│   │   └── gitkeep
│   └── templates/
│       └── gitkeep
├── .github/workflows/validation.yml
├── .codex/config.toml
├── .pre-commit-config.yaml
├── AGENTS.md
└── README.md
```

The `gitkeep` files preserve directories reserved for future artifacts. The
governing plan defines the planned host-specific configuration, systemd units,
deployment scripts, runbook, and test layout.

## Repository ownership

| Information | Source of truth |
| --- | --- |
| NTPsec and client configuration | `homelab-ntp` |
| Host membership, functions, components, and OS facts | `homelab-server-configs/inventory` |
| A, AAAA, PTR, and SRV records | `homelab-dns` |
| Addresses, DHCP, firewall policy, and DNAT | `homelab-network` |
| Munin endpoint configuration and plugins | `homelab-monitoring-observability/Munin` |
| Architecture diagrams | `homelab-docs` |
| Secrets and private keys | Approved secrets manager |

## Validation

Run focused checks from the repository root. For broad or executable changes,
run the full pre-commit suite:

```bash
git diff --check
pre-commit run --all-files
```

The pre-commit Gitleaks hook checks staged files. Its pass does not cover
untracked or unstaged artifacts; scan the working tree before reviewing new
local artifacts or requesting deployment:

```bash
gitleaks detect --source . --no-git --redact --no-banner
```

The repository has no NTP executable or regression suite yet. When the first
collector, installer, or deployment operation arrives, add a focused offline
test, connect it to a path-triggered pre-commit hook, and run that test in this
repository's CI. The shared baseline CI job does not run new NTP hooks by
default. Keep the current fixed-flag shfmt check; add a scoped `--write`
helper only if shell scripts make one useful.

Local checks do not prove GPS/PPS operation, NTP listener state, systemd state,
or UniFi behavior. The governing plan requires target and client evidence for
runtime acceptance.

## References

- [NTPsec Stratum-1 Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
- [Uputronics Raspberry Pi GPS/RTC expansion board](https://store.uputronics.com/products/raspberry-pi-gps-rtc-expansion-board)
