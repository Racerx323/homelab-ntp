# homelab-ntp

Configuration, deployment tooling, and operating documentation for the homelab
NTPsec servers and clients.

> [!NOTE]
> The repository foundation is complete, but it does not contain deployable
> `ntp.conf` files or systemd units yet. Work starts with a scoped read-only
> capture from `j1-svntp1`. The
> [governing implementation plan](ntpsec/docs/ntp-architecture-deployment-plan-v1.0.md)
> records the approved design, deployment state, rollback, and resume point.

## NTP servers

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

The nodes provide independent time service. The design does not use
Keepalived, VRRP, or another NTP HA mechanism.

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

## Project status

- Repository governance and the governing plan are in place.
- The existing live configuration has not been captured or changed under this
  plan.
- Deployable NTPsec configuration, systemd units, scripts, and tests remain
  pending live evidence.
- The next gate defines and reviews the complete read-only `j1-svntp1`
  baseline collector. Execution requires one scoped authorization.

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
│   ├── configs/
│   │   └── gitkeep
│   ├── docs/
│   │   └── ntp-architecture-deployment-plan-v1.0.md
│   ├── scripts/
│   │   └── gitkeep
│   └── templates/
│       └── gitkeep
├── .github/workflows/validation.yml
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
| Architecture diagrams | `homelab-docs` |
| Secrets and private keys | Approved secrets manager |

## Validation

Run repository checks from the repository root:

```bash
git diff --check
pre-commit run --all-files
```

Local checks do not prove GPS/PPS operation, NTP listener state, systemd state,
or UniFi behavior. The governing plan requires target and client evidence for
runtime acceptance.

## References

- [NTPsec Stratum-1 Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
- [Uputronics Raspberry Pi GPS/RTC expansion board](https://store.uputronics.com/products/raspberry-pi-gps-rtc-expansion-board)
