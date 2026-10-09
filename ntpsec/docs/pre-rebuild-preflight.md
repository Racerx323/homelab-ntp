# Pre-rebuild read-only preflight: October 8, 2026

Status: prepared, not authorized or executed. Implements governing plan v1.4
Phase 3.1 before replacing the original j1-svntp1 media and booting j2-svntp1.
Treat each scope below as a separate authorization. None permits shutdown,
clock changes, configuration writes, failure injection, packet filtering,
package installation or service restart. Script exit zero is not rebuild approval.

## Existing current client evidence

Aaron supplied this workstation `ntpq -pw` output on October 8:

| Peer | Tally | Refid | Stratum | Poll | Reach | Delay ms | Offset ms | Jitter ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ntp1.local.theama.co | + | PPS | 1 | 1024 | 377 | 0.645 | +24.115 | 3.736 |
| ntp.local.theama.co | * | PPS | 1 | 512 | 377 | 0.665 | +24.944 | 4.785 |

The primary is selected and the standby is a candidate on this workstation.
This is operator-supplied output, not an agent-run check. Peer display is named;
it does not independently resolve addresses or identify the workstation's IP.
Reach 377 is historical success across the reach register, not proof of future
failover. Similar approximately +25 ms offsets are observed, not accepted
against an agreed accuracy bound. No forced failure is needed for this preflight.

Aaron reports the UDM Beast is configured with both 10.1.0.50 and 10.1.0.51.
Record this independently from DHCP Option 42 distribution. Controller own-NTP
settings, LAN DHCP advertisement and each client's actual daemon configuration
are three distinct facts. Clients should not be presumed to honor DHCP NTP
options or switch immediately. Identify sole-standby clients or explicitly
accept the remaining uncertainty before outage; do not equate the unrestricted
standby outage window with acceptance of unknown client impact.

## R1: primary-node local health

Target: j1-svntp, 10.1.0.50. Proposed SSH account ama, subject to successful
existing authentication and trusted host key; no credential guessing or new
key enrollment. Ordinary user, no sudo. Execution command:

```text
timeout 90s ssh -T -o PermitLocalCommand=no -o ClearAllForwardings=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o ControlMaster=no -o ControlPath=none -o ProxyCommand=none -o ProxyJump=none -o ConnectTimeout=10 -o ConnectionAttempts=1 -o ServerAliveInterval=10 -o ServerAliveCountMax=2 ama@10.1.0.50 'cd / && /bin/bash -s -- --primary'
```

Supply bundled pre-rebuild-health.sh bytes on stdin after checking the approved
bundle hash. No remote staging file. Host key mismatch, unavailable account or
wrong kernel hostname stops the scope. The script discovers one trusted ntpq
in four fixed standard locations and refuses ambiguity; it does not import
standby's executable location as a primary fact.

Collect one local numeric-loopback ntpq system-variable query, one peer table,
uptime and UDP listener listing. Each subprocess has a 12-second timeout.
Hash /etc/ntp.conf before/after without capturing its content; missing,
unreadable or symlinked config stays unresolved. The hash does not prove that
this is the active configuration. Output is one JSON report with argv, return
codes, stdout/stderr, check labels, timestamps and limitations. Exit 64 means
invalid invocation; exit 2 means error/unresolved checks; exit 0 means the
script's limited checks passed, not complete Phase 3.1 acceptance.

Review selected peer identity/PPS, reach, offset/jitter, leap/stratum and UDP
bindings. The machine-check requires leap 00, stratum 1, a nonzero association,
finite offset/rootdisp, selected peer marker, successful commands and unchanged
default-config hash. It imposes no invented accuracy threshold. The human
review must reject questionable peer/quality evidence or mark it unresolved.
No journal, private config or client-list capture is included.

## R2: separate controller audit

Target: `https://udmbt.local.theama.co` (10.1.0.1), local API only. Follow the
[network-owned access procedure](../../../homelab-network/Ubiquiti/UNIFI_ACCESS.md).
Verify endpoint resolution and TLS before authentication. Use only AUDIT_LOCAL
from Doppler project homelab-dev/config prd_unifi, kept in process memory.
No cloud credential, login POST, redirect following or TLS bypass is allowed.
This scope permits endpoint DNS resolution but no DNS-record mutations.

The collector is an agent-operated GET-only review under this exact allowlist:

| GET path | Purpose |
| --- | --- |
| /proxy/network/integration/v1/sites | Confirm local default site, not assume prior UUID |
| /proxy/network/api/s/default/rest/networkconf | Default LAN subnet, VLAN and actual DHCP Option 42 settings |
| /proxy/network/api/s/default/rest/firewallrule | Legacy rule inventory, state/order and references if exposed |
| /proxy/network/api/s/default/rest/firewallgroup | Resolve referenced address/port groups if exposed |
| /proxy/network/api/s/default/rest/routing | Determine whether this controller exposes applicable routing/NAT data here |

One request per path, except repeat the four configuration paths once at the
end for pre/post comparison; 20-second request timeouts, 2 MiB response cap,
no retries. Stop immediately on authentication, authorization, TLS or endpoint
identity failure. A 404/unsupported schema is retained as unresolved, never
proof that no rule exists. These legacy endpoints may not expose current NAT
or zone-based firewall policy. If they do not, stop this stage and propose the
smallest version-specific read-only follow-up; do not guess another endpoint
or claim the desired active target from the architecture plan.

Keep raw responses in memory only. Retain an allowlisted projection: rule/group
IDs, names, enabled states, order, protocol, source/destination addresses/ports,
zone/interface references, translation target and DHCP NTP options/subnet/VLAN.
Never serialize whole network records, which may contain credentials. Preserve
HTTP statuses and parse errors without credential-bearing response bodies.
Hash sorted projected configuration before/after, excluding runtime counters;
missing paths/fields stay unknown. Do not equate this partial hash with a full
controller integrity check. Save only a sanitized projected JSON report.

Determine the effective IPv4 UDP/123 rule and translated target using observed
order, enabled state and references, including both NTP-server bypasses. Do not
assume the planned four-rule count. If possible confirm target 10.1.0.50 and
review affected source ranges. No counter reset or test to an external IP is
allowed. Without packet/counter correlation, label DNAT forwarding untested;
target reachability is separately measured by R3. Broader policy acceptance
remains open. Audit does not inspect private client configurations or establish
the UDM's own time synchronization unless already supplied as operator evidence.

## R3: workstation direct IPv4 probes

Execute bundled pre-rebuild-health.sh --client-ipv4 on this WSL workstation,
ordinary user, no sudo. Exactly one 48-byte NTP mode-3 UDP request to each of
10.1.0.50:123 and 10.1.0.51:123; five-second response timeout per target, no
retry, no DNS and no external destination. It never sets the local clock.
Record actual socket source, request/response hex, validation errors, stratum
and leap. Validate mode/version, length, originate match and nonzero server
timestamps, rejecting KoD and unsynchronized replies. Preserve each failure.

This is one controlled workstation path. WSL NAT may change the wire source;
record this limitation. The supplied Windows ntpq peer table remains separate
client-daemon evidence. No controller, arbitrary-client SSH, IPv6 endpoint,
DNAT-path or future client-failover coverage is claimed by this probe.

## Handling, review and stop gate

Use the existing protected host evidence directory under historical j1-svntp1;
no new per-action directory. Retain R1 as primary-health.stdout/.stderr/.status.json,
R2 as controller-preflight.json, and R3 as client-health.stdout/.stderr/.status.json.
Refuse overwrite/symlinks, use directories 0700/files 0600, and record transport
and script exit statuses separately. Reports must include the approved bundle
hash. Preserve executed bundle, source and failed results; no cleanup is included.
The script itself writes no files; local runner/capture produces these files.

Accept the preflight only after explicit review of all labels:

- PRIMARY: selected primary GPS/PPS, synchronized system, usable listener and
  direct client response; fresh at the eventual shutdown checkpoint.
- CONFIG: unchanged sampled default config/controller projection, with missing
  coverage documented rather than concealed.
- NETWORK: observed active IPv4 redirect target and ordering, reachable target;
  separate unknowns for actual DNAT forwarding and unsupported controller schema.
- CLIENTS: known workstation selected primary; UDM settings reported by Aaron;
  DHCP advertisement observed or unknown; sole-standby population and client
  impact reviewed. Remaining material uncertainty needs Aaron's explicit decision.
- RECOVERY: original card retained, spare verified, KVM usable, primary antenna
  power intact. Reconfirm availability at the eventual maintenance checkpoint.

Any failed or missing label holds shutdown. Evidence collected in a different
maintenance session must be refreshed under a new bounded scope. No stage in
this document authorizes first boot or consumes the separate rebuild approval.
