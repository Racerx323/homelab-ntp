# Debian 11 baseline attempt: j1-svntp1

Collection completed on `2026-09-16` at `21:57:47 UTC`. The result is
**incomplete; baseline not accepted**. This is a sanitized evidence summary,
not an accepted configuration or inventory record.

## Authorization and archive

The user authorized one complete read-only collection, then corrected the SSH
account to `ama`, supplied `ntp1.local.theama.co` / `10.1.0.51`, and reported
the host-key problem fixed. The resumed attempt used numeric IPv4 with strict
host-key checking and noninteractive sudo. It made no DNS query.

Collector SHA-256:
`55868258e5e694fadeef5b862e0c42e8461b99e38931e45d76855e4e25bf5948`.

The exact executed collector and protected evidence are retained outside Git:
`/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/phase1-20260916-attempt02/`.
The original `phase1-20260916/` archive remains intact and records the earlier
host-key failure before authentication. Raw captures must not be committed.

| Check | Observed result |
| --- | --- |
| Remote staging | Root-owned stage and script passed ownership/mode/hash checks |
| Collector invocations | One; no collector retry |
| Collection SSH status | `0`; wrapper successfully recorded collector status |
| Collector exit status | `3`; protected metadata comparison failed |
| Retrieval SSH status | `0` |
| Transfer verification | All 288 transferred files verified by SHA-256; executed script matched approved hash |
| Local protection | Directories `0700`, files `0600`, owned by the workstation operator |
| Command records | 84; six commands returned `127` |
| Snapshot paths | 252 before and after |
| Captured regular files | 113, stored as 112 distinct content blobs |
| Captured file content hashes | All 113 identical before and after |
| Final report | Present; no incomplete-run marker remains; baseline acceptance false |

## Why acceptance remains open

The protected comparison detected modification-time changes only on:

- `/run/resolvconf`
- `/run/resolvconf/metrics`
- `/run/resolvconf/metrics/0000202 eth0.ra`

The last entry's bytes/hash were unchanged; the first two entries are
directories. No protected path membership or regular-file content change was
observed. These runtime timestamps can change during normal operation, but
the archive does not establish the cause. The original exit `3` and failed
comparison remain intact; this review does not relabel them as a pass.

The collector could not find `ntpq` on its fixed system PATH. Four queries
failed: IPv4 peers, IPv6 peers, system variables and associations. Peer
selection, reach, stratum, leap state, offset and jitter therefore remain
unverified. This does not prove ntpq is absent from other installation paths.

`iptables-save` and `ip6tables-save` also could not be found on that PATH.
The separate nftables read completed, but the missing commands remain
collection errors. Unit discovery classified the masked `ntpd.service`
fragment `/dev/null` as an unresolved path in both passes; this is a collector
handling gap, not proof of a service fault.

## Selected observed facts

- Debian GNU/Linux 11 (bullseye); `/etc/debian_version` reported `11.11`.
- Raspberry Pi 4 Model B Rev 1.4, revision `c03114`; reported usable memory
  `3885384 kB`. Firmware power-status query returned `throttled=0x0`.
- Process evidence shows `/usr/local/sbin/ntpd` and `/usr/local/sbin/gpsd`
  running. NTP held UDP 123 listeners on both address families; GPSD held TCP
  2947 listeners on both. This is not a client-response or peer-health test.
- `ntpd.service` was masked/inactive despite the running NTP process. Its
  actual startup ownership must be established before generating deployment
  configuration. Do not infer that the process is managed by that unit.
- `dhcpcd.service` was active/running and `networking.service` active/exited.
  NetworkManager was not found; networkd, resolved and timesyncd services were
  inactive. Effective address/DNS ownership still needs configuration review.
- Passive PPS, RTC, I2C and fan evidence was captured. Device-tree HAT metadata
  was absent. This does not establish physical board revision, antenna wiring,
  stack order, negotiated PoE class, switch port or independent recovery.
- The captured `/var/lib/ntp/leap-seconds.list` expiration parsed as
  `2027-06-28T00:00:00+00:00`; authenticity, effective daemon usage and reload
  behavior remain unverified. No ntpleapfetch invocation occurred.

## Later local review using the deployment guide

The user identified the [original deployment guide](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/).
Review of the already captured unit definitions and full unit-list output
found `timeservice.service` enabled and active/exited. Its captured definition
uses `Type=oneshot`, `RemainAfterExit=yes` and
`ExecStart=/etc/init.d/timeservice start`; a network-online drop-in is also
captured. The v1 detailed unit filter omitted this name. The actual init
script was outside v1's capture set. The follow-up explicitly covers it and
process/cgroup ownership. This finding required no additional node contact
and does not alter the original incomplete result.

## Authorized v2 completion

V2 finished at `2026-09-16T22:14:49 UTC` after one authorized root execution
through `ama@10.1.0.51`. Executed SHA-256:
`ba6dcaea5e98eb02eaeb3dd5aaead99845df42bd01bdab4b60ee9a87d9e1e82f`.

Only four new files were retained in the existing directory
`/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/`:
`baseline-v2.tar`, `baseline-v2.stdout`, `baseline-v2.stderr` and
`baseline-v2.status.json`. No new local action directory or unpacked archive
was created. All four files have mode `0600`; the directory has mode `0700`.
The archive contains the exact executed script, raw output, collector status
and transfer hashes. Earlier evidence remains intact.

| Check | V2 result |
| --- | --- |
| Collection/retrieval SSH statuses | Both `0` |
| Collector status | `2`, incomplete; not an accepted baseline |
| Transfer verification | All 377 files verified without extraction |
| Protected integrity | Passed; 420 paths before/after and all 148 regular-file content hashes identical |
| Runtime telemetry | Three resolver mtime changes recorded separately |
| Commands | 109; two returned `127` for unavailable iptables-save tools |
| ntpq discovery | Trusted `/usr/local/bin/ntpq` selected |
| NTP/GPSD startup | Both process cgroups identify `timeservice.service`; init script and unit captured |
| IPv4 NTP snapshot | PPS `SHM(1)` selected, reach `377`; system stratum `1`, leap `00` |
| Completion evidence | Final report and collector status agree; no incomplete-run marker |

Local response review found errors beyond the report's exit-code checks:

- The IPv6 loopback peers query returned process status `0` but reported
  `Request timed out`. The captured configuration has IPv6 default `noquery`
  and only an IPv4 loopback exception. This is consistent with IPv6 control
  queries being restricted; it does not prove that IPv6 time service fails.
- Six `cv` queries against network-peer associations returned status `0` but
  reported `BADASSOC`. The collector should issue clock-variable queries only
  for established refclocks and recognize error responses independently of
  process exit status. The two SHM clock-variable queries produced no such
  error response.
- `iptables-save` and `ip6tables-save` were unavailable on the collector PATH.
  The nftables read returned status `0` with empty output. This does not prove
  every possible firewall mechanism is absent; do not install tools solely
  to make the collector pass.

No configuration/service/network change, package installation, ntpleapfetch
execution, cleanup, other-node/controller contact or collector retry occurred.
Physical confirmations, complete baseline-app review and independent recovery
remain open. The running-node observations are a snapshot, not rebuild
acceptance or an observation interval.

## Next gate

Review the v2 archive locally against the governing Phase 1 requirements.
Create an observed/unknown/operator-confirmation checklist for baseline apps,
network/DNS ownership, leapfile, hardware and recovery. Assess the IPv6
control-query restriction using captured configuration and startup evidence.
Do not infer that an omitted package name proves an application is absent.

If changing the collector, preserve executed artifacts and add focused offline
tests for ntpq error text despite exit `0`, and refclock-only clock-variable
queries. Preserve unavailable-tool evidence. Define only the smallest remaining
live diagnostic scope and present its new hash for authorization; do not
automatically repeat the full baseline. Reuse the existing local host evidence
directory with distinct files. No further live access or mutation is authorized.
