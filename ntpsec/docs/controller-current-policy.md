# R2b: current UniFi policy lookup

Prepared `2026-10-08`; not executed. Purpose: establish the active IPv4 UDP/123
redirect relevant to rebuilding j1-svntp1 as j2-svntp1. Existing R1/R3 results
and DHCP evidence are retained; do not repeat their successful checks merely
to fill this policy gap. This is a separate read-only controller scope.

## Client-impact decision

Aaron explicitly accepts possible temporary loss of time synchronization on
unidentified clients during the standby outage. This resolves the decision
about unproven sole-standby clients; it does not prove universal failover or
waive primary health, active-redirect evidence, recovery or first-boot approval.
The workstation selects the primary; DHCP advertises both servers. The UDM's
own two-server setting remains operator-reported, not an observed daemon state.

## Target and authentication

Use only `https://udmbt.local.theama.co`, expected IPv4 10.1.0.1, through the
bundled network-owned UNIFI_ACCESS.md procedure. Verify DNS/TLS identity and
use AUDIT_LOCAL from Doppler homelab-dev/prd_unifi in memory. No credential
printing/persistence, cloud credential, redirect following, TLS bypass, login
POST or settings mutation. Do not access either NTP node in this scope.

Previously observed default site UUID: 88f7af54-98f8-306a-a1c7-c9349722b1f6.
Reconfirm its default-site identity once; stop on mismatch. Preserve unsupported
version/schema responses and authentication errors without guessing endpoints.

## GET-only allowlist

Prefix below is /proxy/network/integration/v1. The official
[policy list reference](https://developer.ui.com/network/v10.6.106/getfirewallpolicies)
and [ordering reference](https://developer.ui.com/network/v10.6.106/getfirewallpolicyordering)
identify these integration routes. They document an API version, not the
controller's installed version. Determine installed support from the response.

| Suffix | Bound and reason |
| --- | --- |
| /info | Once; record application version or unsupported status |
| /sites | Once; confirm captured default-site UUID |
| /sites/{siteId}/firewall/zones | At most three pages of 100, 300 records; resolve Internal/External and network membership |
| /sites/{siteId}/firewall/policies | At most three pages of 100, 300 records; inspect enabled IPv4 UDP/123 matches, bypasses and explicit translations if exposed |
| /sites/{siteId}/traffic-matching-lists | At most three pages of 100, 300 records; resolve policy address/port references |
| /sites/{siteId}/firewall/policies/{id} | At most four relevant policy IDs returned above; retain details if list data is insufficient |
| /sites/{siteId}/firewall/policies/ordering | At most two relevant source/destination zone pairs; IDs must come from the returned policies/zones |

Ordering uses sourceFirewallZoneId and destinationFirewallZoneId parameters.
Do not use a policy name alone to infer matching or order. Relevance includes
rules matching all protocols/ports, ranges containing UDP/123, schedules,
source-server exceptions and earlier rules that can override the intended match.
Do not exclude a broad match because its name omits NTP. Retain unresolved
references as blockers. No probes to public NTP destinations or packet captures.

Read policies before resolving zones/lists/order. If the complete bounded
policy list exposes no NAT translation data, move directly to the operator
UI fallback instead of collecting unrelated firewall details.

Repeat only the list/detail/ordering reads once after review for pre/post
configuration comparison, subject to the same bounds. Maximum 32 requests
including metadata; no retries. Per request: 20 seconds, 2 MiB response cap,
GET only. Unsupported or incomplete pagination is unresolved, not empty policy.
Stop on authentication/authorization/TLS failure; retain HTTP status/schema
failure and stop the affected branch on 404/unsupported method. Follow no
response-supplied external URL or arbitrary next-page link; construct only
allowlisted paths with validated UUIDs and bounded offset/limit parameters.

## NAT visibility limitation and operator fallback

Official documentation lookup did not establish a supported dedicated NAT-rule
endpoint. A firewall allow/block policy is not evidence of destination
translation. This scope deliberately excludes speculative private API URLs and
repeated legacy firewallrule/routing queries, which already failed to expose it.

If integration responses lack the translated target or applicable NAT order,
stop API exploration and use Aaron's read-only Network UI capture in this same
review. Required UI evidence is the current IPv4 NTP redirect and surrounding
rule order, including:

- Enabled state, policy name/ID if shown and any schedule.
- Incoming network/interface or zone, source ranges/device groups and bypasses.
- UDP and destination port 123 match, including destination-address restrictions.
- Translated destination IP and port, and position relative to conflicting rules.
- Disabled standby counterpart if present; do not require a fixed rule count.

Capture expanded fields and resolve referenced groups with the already captured
projection or the approved read-only matching-list lookup. No edits, toggles,
Apply/Save, connection flushes, counter resets or export containing credentials.
The agent receives the UI evidence; this does not authorize credential entry,
remote desktop control or UI mutation. If Aaron cannot supply the missing
fields, mark the gate unresolved rather than expanding network scope.

This fallback is part of the proposed scope so an API limitation does not
create another endpoint-guessing/approval loop. It does not convert absent UI
evidence into permission to power down the standby.

## Retention and acceptance

Reuse the existing historical j1-svntp1 evidence directory. Create only
controller-current-policy.json (0600, refuse overwrite/symlinks); optionally
retain the minimum operator screenshots under controller-ntp-policy-*.png.
No new evidence tree or extraction directory. Keep response bodies in memory
and retain only an allowlisted policy projection: IDs/names, origin, index,
action/explicit translation, enabled state, IP/protocol/address/port selectors,
zone/network/group references, schedules and ordered policy IDs. Exclude free
text descriptions, credential/config exports and unrelated client identities.
Record timestamps, request path/status, parse failures and approved bundle hash.

Hash normalized projected configuration before/after; exclude counters/version
metadata, do not drop active schedules or match criteria. Changed projection
holds acceptance. Raw API secrets and Doppler diagnostics must never appear in
output. Retain failures; no cleanup is included. The prior bundle and reports
remain unchanged and provide the existing rule-group/DHCP context.

Accept only when current evidence establishes applicable IPv4 UDP/123 DNAT to
10.1.0.50, with no enabled conflicting standby translation taking precedence,
and no unexplained server-bypass/source-policy mismatch. Direct reachability
of .50 is already evidenced by R3; this lookup does not prove real forwarded
packets traversed DNAT. Report that limit explicitly. If the observed active
target is .51 or another host, stop for an architecture/service-impact decision;
no rule changes are authorized.

Once this gate passes, bind the evidence plus Aaron's client-impact decision
into the final first-boot/recovery authorization. Reconfirm primary/antenna and
KVM readiness at the maintenance checkpoint. No shutdown, card swap, first
boot, client reconfiguration or clock change is authorized by R2b.
