# Pre-rebuild preflight results: October 8, 2026

Approved bundle SHA-256:
`2c261a77056bf754be2eb130fd7ba2597ae2a9daf6330e6c3ce782ad1c9c38af`.
R1, R2 and R3 ran within their read-only scopes. No shutdown, card swap, boot,
clock adjustment, package installation or service/controller change occurred.
**Shutdown remains HOLD.** The immutable executed bundle is retained separately
from repository documentation.

Current disposition: R1 and R3 passed; R2 DHCP evidence and the R2b operator
rule details/list are accepted for the standby-rebuild preflight. Client-impact
uncertainty is accepted. KVM, original-card rollback and primary/antenna
preservation are operator-confirmed. Final first-boot execution still requires
separate approval of its exact bundle. Earlier unresolved findings below record
the sequence of evidence collection; the final R2b section closes the policy gate.

## R1: primary health

The original SSH attempt stopped before authentication: no trusted host key
for 10.1.0.50. After Aaron confirmed trust was established, R1 alone was retried
with identical bundle/script and strict host-key checks. No trust bypass or
agent key enrollment occurred. The failed attempt remains preserved.

Retry transport and script statuses were both 0; all collector checks passed.
The discovered ntpq path is /usr/local/bin/ntpq. Primary j1-svntp reported:

| Observation | Result |
| --- | --- |
| System state | Stratum 1, leap 00, selected association 17767 |
| System offset | 0.006963 ms |
| Root dispersion | 1.816 ms |
| Selected refclock | SHM(1), PPS, reach 377 |
| PPS offset / jitter | -0.0557 / 0.0320 ms |
| GPS SHM(0) | Reach 377, not selected |
| UDP/123 | Primary IPv4, loopback and wildcard listeners observed; no IPv6 client probe performed |
| Default config | /etc/ntp.conf pre/post SHA-256 unchanged |

One upstream, 194.58.207.79, had reach 0; other listed sources and selected PPS
had reach 377. Preserve this degradation without attributing a cause or claiming
all upstreams are healthy. The default-file hash does not prove the daemon's
effective config path. Snapshot results do not establish a sustained time-quality
threshold or replace final Trixie acceptance.

## R2: controller audit

Controller resolution returned 10.1.0.1; TLS verification and local audit-key
GET requests succeeded. Default site was confirmed. All nine allowed requests
returned HTTP 200. Four allowlisted configuration projections were unchanged
between the two reads.

- Default LAN has subnet 10.1.0.1/22, DHCP enabled and DHCP NTP enabled, with
  10.1.0.50 and 10.1.0.51 advertised. VLAN tagging was reported disabled on
  this native network; no VLAN-ID inference was made from that alone.
- Legacy firewall-rule endpoint returned zero records. This is not evidence
  that the active firewall or NTP redirect is absent.
- Routing endpoint exposed one unrelated static route, not the active NAT policy.
- Firewall groups exposed NTP-related ports and addresses; group membership
  does not establish a rule, its enabled state/order or translated target.

At the end of the initial R2 audit, IPv4 UDP/123 redirect configuration remained
**unresolved**; the later R2b sections record its resolution. No current
policy endpoint was guessed or queried outside the approved allowlist. These
partial projections are not a full controller export or integrity proof.
DHCP advertisement does not prove UDM own-NTP health or every client's behavior.

## R3 and operator client evidence

One mode-3 request to each of 10.1.0.50 and 10.1.0.51 returned a valid response:
stratum 1, leap 0, matching originate and nonzero receive/transmit timestamps.
Both checks and the local script passed (exit 0). Socket source address was
10.1.3.141. This is direct workstation reachability, not an external-destination
DNAT test or a server-loss/failover test. No packet retry or clock change occurred.

Aaron's separately supplied workstation ntpq output selected the primary with
the standby as a candidate; both were PPS/stratum 1/reach 377. Its approximately
+24 to +25 ms offsets remain observed client values, distinct from the primary's
local offset. The primary/client measurements describe different clocks.

## Evidence and remaining gates

All files remain in the existing owner-private historical j1-svntp1 directory:

- primary-health.stdout/.stderr/.status.json: first attempt, SSH 255, no script result.
- primary-health-retry1.stdout/.stderr/.status.json: successful user-directed retry.
- controller-preflight.json: sanitized projections, errors/statuses and hashes.
- client-health.stdout/.stderr/.status.json: successful direct probes.

Files are mode 0600. Status records retain bundle hash, command and transport/
script status separately. No per-action directory or additional evidence tree
was created. R2/R3 were not repeated when primary trust was corrected.

Before final first-boot authorization:

1. Rule-detail UI evidence below establishes the primary translation target
   and source/match fields. Obtain the NAT rule-list ordering and relevant
   enabled/paused states to exclude an earlier conflicting translation.
2. Client-impact disposition is now recorded: Aaron accepts possible temporary
   loss of time synchronization on unidentified clients during this standby
   outage. This does not establish universal failover or waive primary health.
3. Reconfirm KVM/old-card recovery readiness and that primary service/antenna
   power remain healthy at shutdown. Refresh evidence if the maintenance
   session changes, under a bounded scope; no automatic reruns.
4. Bind the accepted results into a final first-boot/recovery bundle and request
   its separate approval. Existing candidate hash is not execution approval.

## R2b: current policy API completed; operator UI fallback required

Aaron approved bundle SHA-256
`6c64a58f2d53987a189f4c033fef7130b940310c1f1c551cf42cb7d8d7c7dd4c`.
Four GET requests succeeded: application info, default-site identity, and the
policy list before/after. Controller reports Network 11.0.81; 92 policies were
returned with complete pagination and unchanged sanitized projection hashes.
Policy actions are ALLOW, BLOCK and REJECT; NAT translation is not exposed.
No withheld sensitive fields occurred in the projected policy data.

Stopped the API branch as scoped. No zone, matching-list or ordering requests
were made because they would not establish the missing translation. Retained
controller-current-policy.json in the existing protected evidence directory;
no node access or controller change occurred. Client-impact uncertainty remains
explicitly accepted; the active IPv4 redirect gate is still unresolved.

Use the already-scoped operator UI fallback: capture the IPv4 NTP redirect's
enabled state, UDP/123 match, source/network and exceptions, translated IP/port,
any schedule and relevant rule-list ordering. Include the disabled standby
counterpart if present. Open details read-only; do not toggle, Save or Apply.
Do not rerun the API branch or guess a private NAT endpoint. First boot remains
HOLD until this evidence is reviewed and the final operation is approved.

## R2b: operator NAT detail evidence

Aaron supplied the NTP Redirect detail screenshot and source-list text on
October 8. The observed rule is destination NAT on Default LAN (1),
10.1.0.0/22, IPv4, translating to **10.1.0.50 port 123**. The UI offers Pause,
consistent with an active rule. Protocol is **TCP/UDP**, source port Any,
destination address Any and destination port specifically 123. Match Opposite,
Syslog Logging and Exclude are unchecked. No schedule is shown in this detail.

Source selection is the IP list **Local Device: NTP DNAT**, not all LAN clients.
Aaron's supplied list contains:

```text
10.1.0.3
10.1.0.4
10.1.0.48
10.1.0.52
10.1.1.79
10.1.2.120
10.1.2.130
10.1.3.1
```

The group screenshot corroborates visible entries through 10.1.2.120; the
remaining entries come from Aaron's text. Aaron clarified that Remove beside
10.1.0.4 was copied UI text. The address remains listed; no removal was
requested or performed. Primary .50 and rebuilding-node .51 are absent
from the supplied source list. The screenshot does not establish all other
rules or a complete server-bypass policy.

Translation target and rule match fields are now evidenced. TCP/UDP scope is
broader than UDP-only NTP matching; retain that observed difference for the
later network-policy review without changing it during this rebuild preflight.
Do not infer that all DHCP clients are intercepted by this list-based rule.

At this detail-only checkpoint, still needed: the NAT list showing rule ordering, enabled/paused
states and any standby counterpart. The detail screenshot cannot exclude an
earlier conflicting translation. No live forwarding test is claimed. Keep
first boot on HOLD until that narrow policy check and separate authorization
are complete; do not repeat already supplied rule-detail questions.

## R2b: complete operator rule list and preflight acceptance

Aaron supplied the rule-list screenshot on October 8. Its footer shows
1-36 of 36 records with 100 rows per page. NTP Redirect is the second displayed
row and the only visible Destination NAT rule. The preceding WAS-110 row is
a static route to 192.168.11.0/24 on ISP. The following three translation rows
are Masquerade NAT on Internet 1, ISP and UniFi 5G A; they are not another
displayed Destination NAT rule. No standby DNAT counterpart is shown.

The NTP Redirect row matches the prior details: TCP/UDP, source Local Device:
NTP DNAT, destination port 123 and Default LAN interface. The list has no
explicit enabled-state column; the earlier Pause control supplies the evidence
for this rule's active state. Do not infer other rules' states from text colour.

Taken together, the rule details and complete displayed list establish the
applicable IPv4 UDP/123 translation to 10.1.0.50:123, with no displayed
preceding or competing Destination NAT rule. The supplied source list excludes
both NTP servers. Accept R2b for this standby-rebuild preflight. This establishes
observed controller configuration, not kernel rule traversal, actual forwarded
packets, universal interception or client failover. The absent standby rule
remains later network-policy work before any primary-rebuild transition; no
rule creation or change is included here.

Aaron confirmed KVM access to the rebuilding Pi, preservation of its original
Debian 11 card for rollback, and that j1-svntp stays powered with the shared
antenna and splitter wiring untouched. The local baseline-v2.tar SHA-256 was
rechecked against its retained status record and matched:
`fd4d4c7ec1b900bb41ef3e843f9340dee2e6b5fb660a4b7948f646a32d79b764`.
Archive integrity does not change the historical baseline's unaccepted status.

Next: review and separately approve the final first-boot/recovery bundle. No
shutdown, card swap, boot or live query occurred while recording this evidence.
