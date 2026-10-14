# Installation, configuration, operations and maintenance

This is the single operations recipe. The
[architecture plan](ntp-architecture-deployment-plan-v1.0.md) owns design,
addresses, schedules, hardware constraints and acceptance requirements.
[HISTORY](../HISTORY.md) records accepted milestones and the next deployment
gate. Machine-readable recipes and manifests are supporting installation
assets, not separate plans. A documented or tested procedure is not permission
to contact a node, deploy files, send a notification or reboot it.

## GPSD acquisition before final cutover

The selected NTS association set is `time.cloudflare.com`,
`ohio.time.system76.com` and `oregon.time.system76.com`. The initial time-service
access scope is the governed Default LAN IPv4 subnet and IPv6 ULA subnet;
administrative queries remain localhost-only. These choices do not activate
services or authorize upstream contact during acquisition.

The user selected a separate GPSD acquisition before final configuration.
`configs/gpsd-acquisition-recipe.json` and `scripts/run-gpsd-acquisition.py`
prepare one 900-second observation against the accepted runtime archive,
receipt, cleanup state, exact boot and current governing input hashes. The
[acquisition review](/home/aaron/code/.local-evidence/homelab-ntp/current/gpsd-acquisition-20261013-v1/review.md)
was executed once and accepted as a completed capture, with dual-endpoint
readback and cleanup. Its archive hash is in adjacent `sealing.json`.
The capture does not accept PPS timing or final SHM mapping.

The acquisition temporarily initializes UART termios and starts the
pinned GPSD with `-b -N -n -D 3 -s 115200 /dev/serial0 /dev/pps0`. Receiver writes are
disabled; TCP access remains loopback-only. Pinned `gpspipe` JSON and
`ntpshmmon` samples, GPSD diagnostics and SHM metadata remain private. Do not
infer SHM assignments from example unit numbers. Read-only mode may leave
firmware identity unavailable; record missing evidence and resolve it before
cutover rather than enabling receiver writes implicitly.

The unique root-owned stage clones the accepted runtime context for checks,
preserving original evidence. An independent systemd lifetime limit and
ExecStopPost stop the operation's children and restore saved UART settings.
One start, bounded numbered terminal readbacks, conditional stop/restore and
transient-unit cleanup are defined in the review. Evidence and SHM segments
remain preserved. Boot/identity drift or failed restoration holds acceptance
and requires inspection; no recovery across reboot is claimed.

Capture acceptance requires terminal evidence through both management
endpoints, stopped GPSD, restored UART settings and retained runtime/network
continuity. It does not establish GNSS time validity, PPS accuracy or SHM
mapping. Review the observations before rendering a deployable ntp.conf.
Bootstrap synchronization remains active; ntpd activation, leapfile setup,
Avahi policy/advertisement and external client/NTS acceptance belong to the
later separately approved cutover.

The October 13 acquisition observed 902 TPV reports, all mode 3, and 899 NTP0
samples with leap 0. GPSD decoded NMEA0183 at 115200. Its diagnostic reported
kernel PPS unavailable for `/dev/serial0`; no NTP1 samples were collected.
Both IPv4 and IPv6 readback proved GPSD stopped, UART settings restored and
runtime/network/bootstrap continuity intact. All SHM segments and evidence
were preserved during transient-unit cleanup.

The [corrected v2 acquisition review](/home/aaron/code/.local-evidence/homelab-ntp/current/gpsd-acquisition-20261013-v2/review.md)
was executed once, accepted as a completed capture and cleaned. It explicitly supplies
`/dev/serial0` and the accepted GPIO PPS device `/dev/pps0`, and requests
PPS/TOFF JSON with `gpspipe -P`. It binds v1's accepted terminal evidence,
restoration, cleanup and retained SHM inventory as well as the runtime receipt.
Preflight rejects changed segment identities/ownership or active attachments;
normal GPSD writes may reuse its retained segments. Original evidence is verified
without modification, and before/after continuity and UART restoration remain
mandatory. The pinned GPSD PPS code
supports an explicit PPS device; serial-device autodiscovery failed in v1. Do not infer missing physical pulses from that association failure.
V2 established the explicit serial/PPS mapping: `/dev/serial0` reports TOFF on
NTP0 and `/dev/pps0` reports PPS on NTP2, with 897 independently matching
leap-0 timestamp pairs per source. Both endpoints accepted the stopped/restored
terminal state and retained runtime/network continuity. Final GPSD credentials
were nobody/dialout (UID 65534/GID 20). Retained NTP0 and NTP2 segments are
root-owned with modes 0600 and 0666 respectively; ownership/membership checks
passed without IPC cleanup.

The private `pairing-review.json` binds the capture receipt, cleanup response
and independently reproduced correlation. It records source pairing separately
from timing accuracy. Receiver identity and current runtime/leapfile inputs
are recorded by the short inspection below; final service/client acceptance
remains pending. The earlier private runtime candidate
contains only the serial argument; rerender it with the reviewed explicit-PPS
profile rather than promoting it unchanged. Bind final SHM configuration to
this observed device ordering and ownership; reassess any changed GPSD profile.

The pinned GPSD source (`gpsd/gpsd.c`, `gpsd/timehint.c`,
`gpsd/ppsthread.c` and `clients/gpspipe.c`) establishes the pairing contract:
serial time is supplied to PPS-only devices, and PPS/TOFF reports name their
SHM units when PPS watching is enabled. Allow exactly one serial source and
one explicit PPS source. Correlate reports from each expected device with at
least 60 distinct, matching leap-0 SHM timestamp pairs, requiring different
units. The unit numbers are observed, not predetermined. A pairing observation
does not establish timing accuracy, firmware identity or NTP client acceptance.
Missing or ambiguous samples hold configuration without replaying acquisition.

The checked-in schema-3 acquisition recipe implements the functional gate for
subsequent installations/configurations: within 30 seconds of starting both
monitors, require five distinct, matching leap-0 samples from each expected
device on different SHM units, with all three children still running. Missing,
ambiguous or malformed samples stop acquisition; ExecStopPost restores UART.
Both pinned monitors flush lines, so the check does not wait for process exit.
Only a passing gate permits the remainder of the approved 900-second window;
the completed capture still requires at least 60 matches per source.

The start response waits at most 50 seconds, including socket readiness, for
the durable `functional-gate.json` result. Pending readbacks also expose it.
An unavailable result requires conditional readback/recovery, never another
start. Gate failure is not capture acceptance. Matching dual-stack evidence
of a restored hold permits diagnostic cleanup without accepting samples.
Review the gate and longer window together in the sealed execution scope;
no additional permission is needed for steps already included in that scope.
Cold-start allowances do not replace initial interface validation. The executed
v1/v2 archives retain their original code and evidence; they do not gain this
gate retroactively. Gate success proves source functionality, not UTC accuracy.

### Resolve the remaining cutover inputs

The accepted v2 evidence identifies NMEA0183 at 115200 and the serial/PPS
pairing. The subsequent MON-VER inspection identifies ROM CORE 3.01 (107888),
hardware 00080000, firmware SPG 3.01 and protocol 18.00. Do not infer firmware
from GPSD's VERSION message or the HAT model. Capability strings do not prove
enabled constellations, receiver settings or an exact module variant.

`configs/receiver-runtime-inputs.json` and `scripts/inspect-receiver-runtime.py`
define the short inspection, using the acquisition controller's existing
protected staging, continuity checks, single-use registration and independent
UART restoration. Prepare it offline with the accepted runtime and latest
accepted acquisition/cleanup:

```bash
python3 -I -B ntpsec/scripts/run-gpsd-acquisition.py seal \
    --purpose receiver-runtime-inputs \
    --runtime-dir "$accepted_runtime_dir" --runtime-sha256 "$accepted_runtime_sha256" \
    --prior-dir "$accepted_acquisition_dir" --prior-sha256 "$accepted_acquisition_sha256" \
    --operation-id "$unique_operation_id" --output "$private_review_directory"
```

Use the hashes from the corresponding accepted archives, not a historical
example. The current [receiver/runtime input review](/home/aaron/code/.local-evidence/homelab-ntp/current/receiver-runtime-inputs-20261013-v1/review.md)
was executed once and accepted through both management endpoints; UART
restoration, continuity and cleanup passed. Its adjacent sealing.json binds
the exact bundle. The private `inputs-review.json` independently verifies
the response checksum/decoding and leap-list checksum against captured bytes.

The operation sends exactly one MON-VER request, hex `b5620a0400000e34`, to the
identity-checked UART at 115200, with a 10-second/65536-byte response bound.
This is a receiver query write, not a read-only serial open. It sends no CFG
command, changes no receiver setting and performs no retry or daemon start.
Checksum-valid software/hardware fields and any protocol/module extensions are
retained privately; missing identity holds configuration. Review capability
from the actual response before any later receiver setting is proposed.

The same capture records bounded installed ntpleapfetch and distribution
leap-list contents, existing NTP/supervisor/Avahi configuration, relevant
directories and their ownership/modes, NTP account, UDP 123 listeners and
fixed service states. Its worker has a 120-second limit and restores UART on
exit. Acceptance requires matching dual-stack terminal evidence and unchanged
runtime/network/bootstrap/SHM state. No download, service activation, receiver
reconfiguration or final configuration installation is covered.

Resolve the final inputs in this order:

| Input | Established or required action |
| --- | --- |
| Receiver and GPSD profile | NMEA0183 at 115200; `/dev/serial0` then explicit `/dev/pps0`, receiver writes disabled and loopback-only. MON-VER confirms SPG 3.01/protocol 18.00; retain the observed profile without receiver-setting changes. |
| SHM | Observed serial NTP0 and PPS NTP2, root-owned 0600/0666. Bind the configuration to this exact ordering and verify NTPsec attachment/privilege behavior during cutover. |
| Upstreams/access | All three selected NTS candidates; Default LAN IPv4/ULA service, localhost-only administrative queries. Render the governed subnets and validate both families. |
| Leap maintenance | Installed `/usr/local/bin/ntpleapfetch` is root-owned 0755; the distribution leap list is root-owned 0644, with valid checksum and expiry June 28, 2027 UTC. Select and pin the deployment asset, destination and maintenance command; the checksum alone does not authenticate origin. NTPsec 1.2.5 checks for updates hourly and reports expiry daily, without a default restart. |
| Service/mDNS/runtime paths | `/etc/ntp.conf`, `/etc/ntpsec-timeservice.json`, the combined service unit and `/var/lib/ntp`, `/var/lib/ntpsec`, `/var/log/ntpstats` are absent. NTP account is UID 999/GID 985 with no login shell. Rerender the explicit-PPS candidate and create reviewed writable paths. Avahi is active with IPv4/IPv6 enabled and no explicit interface allowlist; settle its scope before activation. Bootstrap timesyncd remains active and UDP 123 has no listener. |

The pinned source references for leap behavior are `ntpclients/ntpleapfetch`,
`ntpd/ntp_timer.c` and `ntpd/ntp_util.c` in the authenticated 1.2.5 archive.
Do not activate a timer, choose a restart action or accept a leapfile merely
from its presence. Final configuration/cutover remains a separate review after
the captured inputs are incorporated; no repeat long acquisition is needed
just to re-establish the accepted pairing. The final candidate and
execution procedure are defined below. This inspection changed no receiver
settings, started no GPSD/NTPsec process and left bootstrap synchronization unchanged.

### Final service cutover candidate

`configs/service-cutover-recipe.json` and `configs/j2-svntp1-ntp.conf` define
selectable serial NTP0 without calibration, preferred GPIO PPS NTP2, all three
NTS associations, Default LAN IPv4/ULA access and localhost-only queries.
GPSD retains `-b`, explicit serial0/pps0 and 115200. The candidate is not an
accepted live configuration. No APT application packages or receiver settings
change in this stage.

`scripts/run-service-cutover.py` seals the current inputs against the accepted
receiver/runtime archive, matching dual-endpoint receipt and cleanup. It
embeds the frozen accepted prerequisite checker, preserving executed bytes;
this is continuity evidence for this node, not a fresh-node installation recipe.
The new stage rejects changed target/boot, inputs, existing destinations,
unreviewed overrides and SHM membership/ownership. Backups, commands and state
remain under its root-owned 0700 stage, with 0600 evidence. Raw receiver records
remain private. Execution must fit the accepted evidence window.

```bash
python3 -I -B ntpsec/scripts/run-service-cutover.py seal \
    --receiver-dir "$accepted_receiver_directory" \
    --receiver-sha256 "$accepted_receiver_sha256" \
    --network-dir "$accepted_network_directory" \
    --recovered-dir "$recovered_cutover_directory" \
    --operation-id "$unique_operation_id" --output "$private_review_directory"
```

The [cutover review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v1/review.md)
and adjacent `sealing.json` are now preserved execution records. V1 ran once:
the early pairing/ntpd gate passed, but the first convergence probe failed
journal health while NTS associations were still pending. The cumulative
journal criterion could not clear with waiting. Approved recovery restored
original continuity; both endpoints agreed and terminal cleanup completed.
No workstation acceptance was attempted. Do not replay v1.

The saved journal-health output was retrieved by the
[retained-journal review](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-inspection-20261013-v1/review.md)
executed once. Its only retained error-priority entry was NTPsec's
`SYNC: Found 5 servers, suggest minsane at least 3`; this made the cutover's
empty-output journal criterion false. It does not establish an NTS failure.
The supplemental journal query rejected the hyphenated boot descriptor, so
v1 diagnostic acceptance remained held. Current configuration/service metadata and
the final source-file comparison were not reached. Both management endpoints
returned matching partial evidence, and diagnostic cleanup completed while
retaining all files. No services or configuration were changed. Preserve this
executed archive; do not replay it.

`/etc/ntp.conf` was absent before the trial. Recovery therefore removed the
trial configuration; its absence is expected in the restored state. Do not
recreate it outside a separately approved cutover.

The [v2 diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-inspection-20261013-v2/review.md)
executed once and completed with 191 journal records. Both pinned management
endpoints returned identical complete evidence, source-file comparisons passed,
and diagnostic cleanup completed. V1 and the original cutover evidence remain
intact. The accepted diagnostic confirms `/etc/ntp.conf` is absent;
`timeservice.service` and `ntpleapfetch.timer` are absent/inactive, while bootstrap
`systemd-timesyncd` and Avahi are active/enabled. No service/configuration change
occurred. These results accept the diagnostic, not time service.

The trial journal records IPv6 TCP connection refusals for all three configured
NTS-KE endpoints on port 4460, before TLS negotiation. This explains the observed
initial handshake failures; it does not locate the rejecting component or prove
persistent provider failure. No IPv4 NTS-KE attempts are shown in this window.
NTPsec also logged successful mDNS registration, Avahi compatibility warnings,
and later Avahi legacy-unicast response-size warnings. Registration alone does
not establish successful workstation discovery or client acceptance.

The pinned NTPsec 1.2.5 source review found `check_minsane()` counts configured
selectable peers, including the two refclocks, and emits this recommendation at
`LOG_ERR` when at least five are configured and `sys_minsane <= 1`. It does not
measure their health or independence. Selection separately requires at least
`sys_minsane` survivors. With only two local associations, `minsane=3` would
prevent synchronization during loss of all network sources. `minsane=2` would
also require both local associations to survive; NMEA and PPS from one receiver
do not provide independent reference diversity.

Review recommendation: retain `minsane=1` for local-reference availability and
make that choice explicit in a future candidate. This trades quorum protection
for availability when only one source survives. Do not change it merely to
silence the startup recommendation. Any future journal exception must match the
exact expected startup diagnostic, retain its evidence, and reject unexpected
messages, with positive and negative tests. No journal exception, rendered
configuration or cutover acceptance code changed in this diagnostic preparation.
The [UniFi/NTS transport review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-transport-inspection-20261013-v1/review.md)
was executed and accepted for diagnostic collection; both node readbacks matched
and diagnostic cleanup completed. Adjacent `inspection-acceptance.json` and
`outcome.json` retain the receipts and evidence hashes. Current controller evidence
confirms IPv4-only Default LAN NTP/NTS exceptions before a dual-stack reject
covering TCP/UDP ports 123 and 4460. All six IPv4 TCP 4460 probes succeeded;
all six IPv6 probes returned connection refused, across root and the NTP account.
The observed IPv6 egress source was a global address, not the fixed ULA.
This supports the firewall explanation without proving an individual rule hit.
UDP delivery, TLS/NTS authentication and service-sandbox behavior remain untested.

The network owner accepted the v2 automated IPv6 permit correction in
`homelab-network/Ubiquiti/ntp-ipv6/`. Its two enabled IPv6-only rules
match the observed Ethernet MAC for UDP 123 and TCP 4460 before the existing
reject. This avoids storing a changing global IPv6 address or distributing an
API credential to the NTP host. Fresh MAC/eth0-route checks and post-change
IPv6 connectivity must validate the candidate; a changed NIC or routed topology
requires a new review. No host address or prefix change is included.

The candidate binds backups, disabled creation, ordering, enable readback,
conditional exact-object recovery and fresh before/after TCP diagnostics. It
preserves original rules and return policy and stops on unrelated drift. There
is no independent gateway recovery timer; interrupted work may require the
approved recovery continuation. UDP traffic, authenticated NTS and client
acceptance remain cutover gates. V2 policy and TCP checks are accepted. Carry the
mDNS warnings into the next client-acceptance review.

V1 execution held before any firewall write: its accepted before-capture found
the IPv6 DNS allow rule had changed from an address-list source to MAC matching.
The old list was consequently not referenced/retrieved; deletion is not inferred.
The NTP probes still showed six IPv4 successes and six IPv6 refusals. Matching
readbacks and diagnostic cleanup completed; no rollback was required. The
separately approved v2 preserved that observed DNS configuration. All six IPv6
TCP probes then succeeded, alongside all six IPv4 probes, across the three
upstreams and root/NTP contexts. Before/after readbacks matched and cleanup
completed. Both new rules remain enabled; no recovery or service start occurred.
Preserve both executed bundles and v2's private acceptance/outcome receipts.

The corrected [v2 cutover review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v2/review.md)
ran once and recovered; its adjacent `sealing.json` identifies the preserved
archive digest. It binds the accepted network outcome, policy
receipt, matching after-capture readbacks, controller receipt and diagnostic
cleanup alongside the accepted receiver/runtime inputs. The original freshness
window remains unchanged; live preflight must still reject target drift.

The candidate explicitly sets `tos minsane 1`: a lone surviving source may
synchronize the node, without a multi-source quorum. NMEA and PPS share one
receiver. Raising the setting to three would prevent local-only operation.
The tested journal checker queries JSON with the compact boot ID, then filters
by the saved monotonic apply time. It permits at most one exact error-priority
`SYNC: Found 5 servers, suggest minsane at least 3` record from the current ntpd
child's syslog transport within 120 seconds of apply. Unexpected messages,
provenance, duplicates and late advisories block acceptance. Malformed records
or a boot mismatch fail closed. The informational stderr copy requires no
exception. Raw journal records and classification remain private evidence.

V2's early GPSD/SHM and localhost ntpd gate passed. Its first convergence probe
allowed the one expected minsane record but rejected six other error-priority
records: three `NTSc: read ... bytes` and three `NTSc: Got 8 cookies ...`.
Each NTS association reported seven available cookies. PPS reach/selection
and authenticated NTP packet acceptance were still pending at that first probe;
no later convergence or workstation checks were attempted. Waiting could not
clear the cumulative journal failure, so the approved recovery ran immediately.
Both management endpoints confirmed the same recovered state, and terminal
cleanup completed. `/etc/ntp.conf` is again absent, GPSD/NTPsec stopped, and
bootstrap timesyncd restored. Preserve the stage, archive and private outcome.

Offline review of the pinned NTPsec 1.2.5 archive confirms `ntpd/nts_client.c`
lines 714 and 870 log the read-byte and cookie-count records at `LOG_ERR`;
the cookie-count message precedes a successful return. Cookie acquisition does
not establish authenticated UDP time exchange. Next correct and test journal
classification against these source-backed diagnostics before sealing another
cutover. No additional exception, replay or live change is authorized by this
outcome; preserve rejection of actual TLS/NTS failures and all other gates.
Retain early functionality, UDP/NTS authentication, clock discipline, workstation
dual-stack NTP, mDNS and recovery requirements. TCP success alone does not accept
the time service or authorize replaying the earlier cutover.

The corrected [v3 cutover review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-cutover-20261013-v3/review.md)
ran once and recovered; the adjacent `sealing.json` identifies its preserved digest. In
addition to accepted receiver/runtime and firewall evidence, it binds v2's
archive identity, specification, matching recovered-state receipts and terminal
cleanup. Original freshness bounds remain in force; live preflight must still
revalidate the target. Executed v1/v2 artifacts remain unchanged.

The v3 classifier retains the single minsane allowance and adds exactly two
NTPsec response formats, with the pinned source's bounds: read sizes 1–2048,
cookie counts 1–8, lengths 1–192 and AEAD IDs 15/16/17. Allow at most three
read records and three cookie records with equal totals, all from the current
ntpd child's syslog transport within 120 seconds of apply. These totals bound
startup telemetry; the messages do not identify which upstream produced them.
Repeated identical records, excess counts, wrong provenance, late records,
invalid values and other errors block acceptance. Partial read/cookie totals
remain unhealthy until balanced. Independent checks still require all three
named associations to authenticate NTP packets, have reach and retain cookies.

Tests replay the observed message sequence, verify source-bound endpoints and
reject TLS/connection/AEAD/cookie failures and altered recovery receipts. An
offline check of all seven retained v2 error-priority records also passes the
new classifier. Preparation changed no receiver, firewall or running service.
V3 subsequently executed once; its early gate passed and journal health passed
at every probe. Five probes covered about 334 seconds from apply. PPS became
reachable and selected, but its fifth-probe offset was +45.720453 ms and jitter
38.583872 ms, outside the 5 ms/1 ms limits. Every NTS peer retained cookies but
had reach zero throughout. Neither authenticated packet acceptance nor the
three-consecutive-pass requirement was met; workstation checks were not run.

The approved failure path recovered early, without exhausting the 40-probe
budget. Both management endpoints confirmed the same recovered state, and
cleanup completed. Bootstrap timesyncd and the original files/UART were restored;
`/etc/ntp.conf` is absent again. Preserve the v3 archive, command log, generated
runtime statistics, probes and private outcome. No classifier exception or
acceptance threshold was changed during execution.

Next prepare a scoped diagnostic review for retained logs/statistics, NTS packet
accept/reject counters and the UDP request/response path, plus startup clock
selection/discipline. Separate retained read-only collection from any probe or
service restart needing explicit scope. The current evidence does not identify
where packets were lost/rejected or establish the cause of the PPS transient.
Do not infer another firewall defect, calibrate serial time or relax acceptance
from these samples. Do not replay v3.

### Retained NTS/PPS diagnostics after v3

The [retained NTS/PPS review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-retained-20261013-v1/review.md)
was executed once under its sealed approval. Matching dual-stack readbacks
accepted diagnostic retrieval; cleanup preserved the source and diagnostic
artifacts. The adjacent `outcome.json` binds acceptance, cleanup and result
hashes. It does not accept time service or authorize another trial.

The capture recovered 287 journal records, five saved journal probes and six
statistics files (current/dated copies of three streams). Two loopstats updates
308 seconds apart show frequency changing from zero to 148.443029 ppm; this
supports, but does not prove, startup frequency estimation. All three NTS-KE
exchanges succeeded. Missing packet rejection counters and wire observations
leave the cause of zero upstream reach unresolved. Timeservice and `/etc/ntp.conf`
remain absent; bootstrap timesyncd is active. No target configuration changed.

Local review of the five saved samples found system frequency zero through
246 seconds, then 148.443 ppm at 334 seconds. The pinned NTPsec 1.2.5 source
uses a default 300-second stepout interval; its NSET/FREQ path defers initial
frequency estimation until that interval. This is consistent with startup
training, not proof of the runtime state or a steady-state PPS error. Recovering
at 334 seconds did not establish settled performance. The retrieved journal
and statistics do not justify calibration or threshold changes; retain both
unchanged.

The v3 pairing evidence confirms serial NTP0 and GPIO PPS NTP2; the candidate
already marks PPS preferred. Another host's NTP1 assignment does not replace
this observed mapping. The user-supplied other-host snippet has no explicit
`prefer` modifier despite its comment; its actual GPSD mapping was not inspected.

`run-cutover-inspection.py` now accepts the exact legacy and compact-boot journal
command profiles, with 1–41 retained probes, rather than assuming one legacy
probe. It copies the before/state/command files and recovery-preserved
loopstats, peerstats, clockstats, drift and leap temporary files. Statistics use
closed names, at most 12 regular single-link files and 2 MiB combined; source
files are capped at 8 MiB and aggregate retrieved evidence at 8 MiB. Missing or
empty statistics are reported explicitly. Compare saved bytes and statistics
membership again before acceptance. The original stage remains locked read-only.

One retrospective timeservice/Avahi journal query covers the pinned boot and
trial time window, bounded to 2 MiB and 1999 complete records; reaching 2000
holds acceptance. Inspect only fixed service states and `/etc/ntp.conf` metadata
otherwise. Use protected root-owned staging, a 90-second worker, matching
dual-stack terminal readbacks and diagnostic cleanup. Preserve all evidence.

```bash
python3 -I -B ntpsec/scripts/run-cutover-inspection.py seal \
    --source-dir "$recovered_v3_directory" \
    --source-sha256 "$executed_v3_sha256" \
    --operation-id "$unique_operation_id" --output "$private_review_directory"
```

The saved localhost queries did not collect NTS packet rejection counters, and
stopped-daemon counters cannot be recreated. This first review does not include
packet capture, network/controller queries, upstream probes, service activation,
clock changes or receiver I/O. It may identify logged rejection or startup-state
information; it cannot by itself locate packet loss or prove UDP reachability.
After accepting the retained evidence, define any remaining active packet/counter
capture separately. Do not label missing historical data a successful check.

### PPS-led cold-start diagnostic (legacy bounded profile)

The diagnostic recipe enables `pps-startup.py` through `timeservice.py`. It
renders a private PPS-only bootstrap from the unchanged final profile and
promotes sources in the same ntpd process. The ordinary service recipe does not
enable this cold-start-only policy. Persistent restart behavior with an existing
drift file needs a separate policy before service cutover. This diagnostic
refuses that file rather than assuming a cold-start event sequence on restart.

1. Run the existing bounded GPSD serial/PPS pairing gate. Bootstrap with only
   selectable, preferred SHM2 PPS; defer SHM0 and all three NTS associations.
   GPSD still consumes serial time to associate the PPS pulse with its second.
   Require PPS selection within 120 seconds and retain the same daemon PIDs.
2. Require `freq_mode`, a later `freq_set`, then `clock_sync` from that ntpd
   process. The initial startup `freq_set` is insufficient. Parse pinned 1.2.5
   `PROTO:` messages with matching event codes, boot/PID and monotonic time.
   Never infer initialization from nonzero frequency or seed the recorded
   159.7 ppm startup estimate.
3. After at least 600 seconds, require three distinct PPS updates within
   5 ms offset/1 ms jitter, selected PPS, leap zero and stratum one. Each update
   must advance the receive counter, receive timestamp and refclock poll counter;
   repeated queries cannot count. The bootstrap deadline is 900 seconds. A clock
   step after qualification begins, counter reset or replaced association fails.
4. Add selectable SHM0 and all three reviewed `nts iburst` servers through
   authenticated localhost Mode 6, without restarting ntpd or replacing PPS.
   Persist submission before each command and never replay a timed-out mutation.
   Require authenticated acknowledgements and the expected association membership;
   partial promotion fails. NTS setup grace starts at promotion. Require three
   fresh passing PPS updates with reachable NMEA and all three authenticated,
   reachable NTS sources before declaring startup ready.
5. The helper's completion deadline is 1500 seconds after ntpd launch; the outer
   diagnostic ends no later than 1500 seconds after apply, preserving the
   independent 1800-second recovery timer. Every diagnostic outcome restores the
   baseline. Service/client/mDNS acceptance remains a separate cutover stage.

The per-start control key and bootstrap configuration live in root-owned
mode-0700 `/run/ntpsec-startup`, with file mode 0600. The supervisor removes them
when its children stop; promotion status remains available for recovery evidence.
Keys and MACs do not enter command logs or readback. Administration remains
localhost-only. The pinned client needs 4-byte request alignment and 8-byte
response alignment; the single-threaded helper applies that compatibility rule
and rejects an invalid response MAC. It bypasses the client's automatic retry.

Every diagnostic activation repeats bootstrap. A future persistent restart policy
must preserve this ordering while handling verified saved drift. There is no
permanent `noselect`, changed polling, guessed `time1`, drift seed or relaxed
threshold. Durations are bounds, not convergence guarantees. Recovery preparation
selects the unique terminal dual-stack readback matching the receipt; retained
v4 evidence selects attempt 11 without relabeling earlier evidence.

The opt-in `tests/test_pps_promotion_linux.py` fixture exercised a local build of
pinned NTPsec 1.2.5 in rootless network/IPC namespaces. Authenticated commands added
SHM0 and all three NTS associations, preserved the PPS association and daemon PID,
and rejected a wrong key without adding an association. A deliberately corrupted
response MAC was also rejected. There was no outside
network, and the daemon could not adjust the host clock. This proves local Mode 6
compatibility, not upstream NTS authentication, PPS discipline or target
acceptance. Offline tests cover timing transitions, stale samples, provenance,
deadlines, uncertain/partial promotion and cleanup. The v5 trial below recovered on its first journal-health check; promotion was not reached.

### Retained PPS policy review

The [offline replay](/home/aaron/code/.local-evidence/homelab-ntp/current/pps-policy-review-20261014-v1/review.md)
matches the frozen helper against all 30 retained supervisor snapshots. Stored
qualification began at 836.743 seconds; only two peer-statistics updates met
the quality limits before shutdown, at a 64-second cadence. The final retained
supervisor snapshot records one qualifying update. A later statistics row is
not a complete acceptance sample. The 900-second bootstrap bound prevented
three qualifying updates on the observed trajectory; longer observation has
not been demonstrated to pass.

The earlier 1080-second proposal is superseded by the operator's decision to
keep PPS-first isolation and monitor convergence without a timing-quality
shutdown deadline. No duration guarantees convergence. The version-1 diagnostic
remains a bounded, mandatory-recovery operation; it cannot implement this decision.

### Continuous PPS-first monitor candidate

`configs/pps-monitor-policy.json` supplies the exact version-2 `pps_startup`
object for a future rendered timeservice configuration. `pps-startup.py`
implements it without a first-selection, qualification or completion deadline.
The existing serial/PPS pairing gate still requires five matched samples per
source within its bounded startup window. A cold receiver that cannot satisfy
that gate needs acquisition first; this candidate does not wait indefinitely
for missing receiver functionality. Existing drift files remain rejected until
a separate warm-restart policy is implemented.

The helper observes every 30 seconds while qualifying. After at least 600
seconds and ordered frequency initialization, require three distinct fresh PPS
updates within the unchanged offset/jitter, selection, leap and stratum limits.
Promote selectable NMEA and all three NTS sources once through authenticated
localhost control, without restarting ntpd. Continue 30-second observations
until three fresh PPS updates also have reachable NMEA and authenticated,
reachable NTS sources. Then observe every 300 seconds. Degraded timing,
unreachable sources or a clock step reset qualification and resume the faster
cadence; they do not stop the pair or repeat promotion. Alternative selected
sources after promotion are recorded rather than treated as process faults.
Process/association discontinuity, counter regression, unexpected membership,
authentication failure and uncertain mutation remain failures that stop the pair.

The rendered configuration must bind `pps_monitor_evidence` to
`/var/lib/ntp-acquire-<operation-id>/startup-monitor.json` in its root-owned
0700 operation directory. Reject an existing record and unsafe ancestry. Write
owner-private bounded status there before updating `/run/ntpsec-startup`.
Retain up to the latest 120 observations, total sample count, latest measurement,
machine state, command acknowledgements and terminal reason, with a 512 KiB
record bound, evicting oldest observations when needed to fit. Raw keys, control authentication payloads and packet captures
are not recorded. Incremental, boot/PID-bound journal reads retain initialization
progress without repeatedly scanning the complete lifetime journal. A failed
evidence write must not block daemon or credential cleanup. Last observed ready
state plus a terminal `running=false` record is not a running-service claim.
An uncatchable kill or power loss leaves only the last persisted observation;
missing terminal metadata must not be inferred as a clean stop.

### Start-and-monitor activation and recovery

`scripts/run-service-monitor.py` seals an independent activation stage against
the accepted restoration archive, receipt, matching dual-stack readbacks and
closure. The [executed review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v1/review.md)
stopped in preflight on the nested hardware acceptance gate. Conditional readback
found no operation state file; installation/watchdog arming was not reached.
Preserve the partial stage and executed bundle; do not replay start or run
recovery/cleanup without the required state and receipt. The retained hardware
acceptance exceeded its 24-hour limit on October 14 at 11:41:04 a.m. CDT.
This establishes a freshness blocker, not a physical hardware failure.

The initial guard capped sealing at the nested expiry. Schema-2 monitor preparation
now requires a separately accepted revalidation archive, matched readbacks and
closure; it cannot be sealed from the historical hardware receipt alone. The
new start window ends no later than the revalidation window or 24 hours after
its observation, with 600 seconds reserved for installation. Do not rewrite
historical acceptance timestamps. The original frozen checker remains unchanged.
The old diagnostic remains unchanged and
always restores; its expired window is not extended by this operation.

#### Read-only prerequisite revalidation

The [revalidation v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v2/review.md)
used `scripts/run-runtime-revalidation.py`; its approved capture passed all seven
prerequisite checks. Readback attempt 1 matched through both endpoints and
diagnostic closure completed. Monitor v2 consumed that prerequisite and later
recovered. A replacement revalidation must bind the recovered monitor before
another activation review. Activation still requires separate execution approval.
V1 remains closed with `validation_held`, matching dual-stack readback and diagnostic
closure; its receipt cannot authorize activation. V2 uses the frozen validator's
`/var/lib/ntp-acquire-<operation-id>` path contract. Sealing exercises the same
runtime alias validation as preflight, and start checks the local review/spec
against the archive before registering execution. A missing SSH-agent reference
rejects locally without consuming the one-shot start.
It binds either the exact preflight-failed monitor archive/rejection/readback or
the recovered monitor archive, matching recovered readbacks, receipt and cleanup.
For a preflight failure, require no operation state, backups or monitor record.
For recovery, require the exact terminal state including transient cleanup.
Require absent prior workers/timer in both cases; preserve all prior files. Hold the original
source lock, verify immutable source/restoration members and idle recovery state,
then recheck prerequisites using a new root-owned 0700 stage and private copies.

`runtime-continuity.py` requires the historical hardware state to match its sealed
closure exactly, plus the bound spec/receipt, current boot, boot-file hashes and
live UART/PPS/RTC mapping/permissions. It changes no acceptance timestamp. The
original runtime probe then checks packages, native/Python paths, accounts, loader
cache, network and protected files through that current-hardware checker. Compare
the fresh observer result with accepted restoration continuity and recheck source
immutability. This validates metadata and prerequisites, not physical PPS quality
or time service. Existing bounded network/egress probes remain included.

Offline regression coverage traverses the real alias validator, transaction
constructor, preflight and runtime context with simulated host I/O. It covers
success and drift rejection, lost transport without replay, expiry-safe readback
and closure, and worker timeout/missing-report evidence retention. Preserve the
frozen observer's stderr rejection and require true boolean checks, integer epochs
and bounded evidence in accepted receipts. These checks do not establish live
hardware/runtime acceptance.

One 180-second capture retains complete evidence or a held report. Reserve 190
seconds before its start-window end. Up to three numbered dual-stack readbacks
retrieve the stored report; matching complete results accept prerequisites only.
Conditional cleanup records closure without deleting any stage or changing
services/timers. No boot changes, daemon activation, configuration/receiver writes
or clock adjustment are included. Preserve incomplete evidence on failure.

The successor monitor uses the same sealed continuity helper in preflight and
post-restoration validation. Handoff uses the new operation's protected preflight
observation, bound to the accepted revalidation digest, for packages/boot/Python;
it retains native, account, loader, network, hardware and file checks. Offline recovery tests
advance past historical expiry, restore original files and still reject live
boot-file drift. Recovery has no receipt-age shutdown; its identity/content checks
remain mandatory. Legacy cutover paths retain their original checker. Fresh
revalidation must execute and be accepted before a new activation can be sealed.

The [executed monitor v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v2/review.md)
binds accepted revalidation v2, readback attempt 1 and diagnostic closure, plus
the accepted restoration. Startup and early/workstation checks passed, but
handoff rejected the inherited comparison with the historical runtime boot ID.
Approved recovery completed; readback attempt 2 matched through both endpoints
and transient cleanup completed. Preserve this executed operation, backups and
terminal evidence. The inherited handoff correction and full-path offline tests
are complete. [Read-only revalidation v3](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-revalidation-20261014-v3/review.md)
executed once against recovered monitor v2 and its matching readback attempt 2
and cleanup. All seven checks passed. V3 readback attempt 1 matched through both
endpoints, and diagnostic closure completed with evidence preserved. Its digest
is in adjacent `sealing.json`; `acceptance.json` accepts prerequisites only.
The successor validator accepted the actual receipt/readbacks/closure offline.
The [monitor v3 review](/home/aaron/code/.local-evidence/homelab-ntp/current/service-monitor-20261014-v3/review.md)
was executed once against accepted revalidation v3. Startup and workstation
structural checks passed; handoff failed with
`one GPIO PPS platform and class required`. Readback attempt 1 matched
`observing`; approved operator recovery completed, readback attempt 2 matched
`recovered` through both endpoints, and transient cleanup completed. Preserve
its recovered receipt, terminal startup record and all source evidence. No
continuous-monitor handoff or timing acceptance was achieved. Do not replay it.
The repository PPS correction is implemented and tested offline. The standalone
`check-pps.py` accepts an explicit GPIO mapping JSON and its SHA-256; it performs
metadata reads only and returns selected identity, bounded class/platform inventory
and a rejection reason. Host configuration delegates to that tool. New runtime
revalidation and monitor manifests pin both current hardware and PPS checkers;
the successor rejects checker bytes that differ from its accepted prerequisite.
The monitor retains handoff PPS observations in operation state before recovery.
The actual hardware checker now participates in the handoff regression fixture;
an additional unrelated PPS class passes, while missing/duplicate sources,
character-device changes and accepted mapping drift fail.

### Deployment artifact contract and historical data

All executable artifacts come from maintained repository sources. Configuration,
baselines, target identity and code versions are explicit hash-bound manifest
inputs. A current baseline means an explicitly accepted revision, never a mutable
`latest` lookup. Evidence remains a data/provenance input or output; it must not
supply executable implementations. This applies to all deployment artifacts,
not only the PPS checker. Historical executed bundles remain immutable.

New revalidation, monitor and standalone lifecycle bundles implement this contract:

| Path | Maintained implementation and data boundary |
| --- | --- |
| Acquisition and restoration readers | `runtime-artifacts.py` validates historical manifests, target identity, receipts and closure using current acquisition/restoration schema readers. Archived code is never imported. |
| Runtime reconstruction | Current manifest members supply the helper, hardware/PPS checkers, network checker, inventory reader and supervisors. Historical configuration/baseline members remain unchanged; an effective specification pins the substituted code. Unknown historical Python members reject. |
| Revalidation and monitor preflight | Both seal current repository sources. Monitor requires identical code to the accepted prerequisite, including receipt readers and runtime dependencies. Preflight, handoff and recovery use the resulting runtime copy. |
| Standalone acquisition | Pins the helper and complete runtime implementation set; rebuilds runtime checks from unchanged historical data and current code. Rechecks the effective specification and member hashes. |
| Standalone restoration and hardware recovery | Pins maintained receipt readers, recovery implementation and runtime checkers. The historical stage remains the data/state root; executable imports use the new code root. |
| Retained inspection and fresh baseline | Pins current helpers and continuity observer. A historical observer digest binds retained bytes as data, independently of the observer executed now. |

The superseded `run-service-cutover.py seal` entry point rejects new trials.
Historical bundles retain their original execution behavior and evidence; this
migration does not retroactively validate them. New preparation rejects changed
repository code, including the transitive runtime helpers.
Read-only revalidation v4 was accepted on October 14 through matching IPv4/IPv6
readbacks using maintained sources; diagnostic closure completed. Hardware,
runtime, restoration, continuity and idle-worker checks passed. Monitor v4 then
passed structural handoff and reached PPS qualification at about 963 seconds.
Promotion commands were acknowledged, but its immediate membership snapshot
lacked NMEA. The checker triggered automatic recovery; dual-stack readback
attempt 1 matched recovered state and transient cleanup completed. Preserve the
terminal monitor evidence and monitor-v4 recovery records. The offline promotion
analysis and permission correction below precede another sealed operation.
No prior approval transfers to changed
code; sustained timing and production acceptance remain pending.

Offline promotion analysis identifies a privilege mismatch: NMEA is omitted at
startup, then its root-owned 0600 SHM segment is attached after ntpd drops to the
dedicated account. An isolated network-free permission test reproduces denial.
Pinned NTPsec can acknowledge parser success while dropping a refclock whose
attachment fails; command acknowledgment alone is insufficient. The original
target SHM error has not been retrieved, so distinguish this diagnosis from a
captured target errno. Longer settling does not resolve the permission barrier.

The monitor implementation now grants reversible access to the accepted NMEA
segment using repository-owned `shm-access.py` and `shm-access.c`. Preflight
validates the ntp account/group and accepted NTP0 key, shmid, creator, size and
root:root 0600 metadata. It builds the native helper against the target's system
headers, records compiler/source/executable hashes, and pins the kernel sequence
and change time in a protected receipt. The compiler must already be installed;
this stage does not install dependencies. Before either daemon starts, the stage
persists grant intent and changes only NTP0 to root:ntp 0660. Handoff checks the
exact grant and leaves other SHM entries under their original continuity checks.

Recovery stops both consumers and confirms idle state before restoring the same
segment to root:root 0600. Write-ahead receipts cover interruption before or after
either metadata change. Unexpected permissions, a changed identity or remaining
attachments hold recovery. IPC_SET updates the kernel change time; recovery
records that new value rather than pretending to restore the old timestamp.
The helper never creates, removes, attaches to or writes sample data in SHM.
Promotion retains bounded raw configuration replies, association measurements
and provenance-checked refclock/error journal entries before recovery. Parser
acknowledgment still does not satisfy the association membership check.

Offline tests exercise real permission changes and credential-drop attachment in
a disposable private IPC namespace, plus interrupted restoration and the actual
handoff/recovery paths with external I/O fixtures. CI repeats the native test
under `unshare --ipc`; workstation validation uses offline Podman with a private
IPC namespace. These results do not establish target acceptance. Prepare fresh
revalidation against monitor-v4's recovered records before a new monitor review;
keep each execution separately hash-approved. A duplicate refclock command
does not provide a verified way to clear a preloaded noselect association.

### Evidence retention and package pruning

Retain unique observations, receipts, manifests, approvals, recovery records and
current operation inputs. A failed operation does not require every duplicate
package to be kept at every historical pathname. Before pruning a package, record
its exact path and SHA-256, verify a byte-identical retained copy, and document
how to recover it. Preserve nested archive member paths and the retained archive's
hash. Never remove the sole copy or alter executed bundle bytes.

The private audit supplies an exact deletion manifest; auditing is not deletion
authorization. Removing a duplicate package can make its original local command
unusable until that package is restored. Do not remove entire operation directories
or infer that unique logs are disposable merely because the operation failed.

The approved October 14 retention sequence is complete: 8,439 exact duplicates
removed; 4,010 unique files and nine symlinks archived, restore-tested and retired
from their old paths; all 328 protected files reverified. The private archive's
member manifest, recovery-location ledger and Git bundle preserve retrieval.
Original directories remain. The audit inventory describes the pre-cleanup state
and must not be replayed as another deletion plan.

All 117 pinned installation assets and both publisher signatures now verify in
one explicitly supplied private cache. The three missing payloads were fetched;
the other 114 were reused. Verification does not install packages. A clean checkout
needs that cache, repository verification keys and explicit target observations;
it does not need duplicate historical package directories.

Clean-directory offline tests exercise maintained code with synthetic historical
data. They do not prove a fresh host deployment end to end: acquisition still
requires a previous accepted capture, and monitor preparation requires restoration
and revalidation receipts. These continuation prerequisites need a separately
implemented first-install entry path before claiming an unattended fresh install.

The old-action audit covers these reachable dependencies:

| Reference | Required use and checks |
| --- | --- |
| Original receiver/acquisition archives and retained SHM inventory | Immutable evidence of serial/PPS pairing and segment ownership; recheck members and retained bytes. Normalize only live attachment counts during activation. |
| Accepted hardware/runtime and native-build artifacts | Immutable provenance; recheck current boot, boot files, mappings, accounts, loader and installed content. Never renew old timestamps. |
| Original held diagnostic and restoration | Preserve held state exactly under its source lock; verify restoration report/closure and inactive old timer. |
| Latest recovered monitor | Bind archive, recovered receipt, matching readbacks and cleanup; verify live stage members/state and absent workers before and after capture, and again before activation. |
| Accepted prerequisite revalidation | Bind report, closure and exact checker bytes; require the full fresh observation to match at activation preflight. |
| New activation's preflight and supervisor | Compare handoff identity with its protected, digest-bound observation. Inspect current child PIDs and credentials; permit only the exact scoped startup journal reader alongside GPSD/ntpd. |
| New activation's backups, watchdog, fault unit and monitor record | Derive paths from its unique operation specification; recovery and cleanup address only this operation. Preserve all source stages. |

Retained observation fields include SSH/NetworkManager service PIDs, but exclude
Avahi/timesyncd. Their restart during recovery does not establish a stale-PID
mismatch here. Keep exact observation comparison; no PID normalization is added.
The only confirmed stale identity was the inherited historical boot-ID check.
The journal-reader race is an offline code finding, not the observed v2 failure.
Regression tests run the inherited unchanged/measurement and handoff path with
simulated host I/O, including real drift rejection and watchdog retention.
The retained monitor archive exceeds 32 MiB. Revalidation and monitor staging
therefore allow sealed archive members up to 64 MiB, while ordinary stage members
and reports retain their 32 MiB bounds and captured evidence remains capped at
8 MiB. Archive parsing keeps flat-file, duplicate, manifest and aggregate bounds.
Sealing checks the complete archive again before issuing its digest.

Before mutation, freshly verify the restored baseline, native/runtime/network
and hardware prerequisites, held source state, protected restoration members,
idle old recovery worker and inactive old timer. Require exact current-boot
continuity with the newly accepted revalidation observation. Drift stops the stage.
Root-owned 0700 staging binds current inputs and a unique operation identity.
Back up destinations, arm a 600-second installation watchdog, install the
rendered configuration/service and fault-recovery unit, then start once.
The short receiver gate and localhost ntpd response must pass before handoff.

Handoff requires both pinned SSH endpoints, unchanged protected configuration,
daemon identities/credentials, a fresh live monitor record and workstation
IPv4/IPv6 NTP responses with administrative queries denied. Leap-3/stratum-16
responses are allowed for this structural check; no timing acceptance is issued.
Only successful handoff cancels the watchdog. A queued watchdog checks committed
state under the operation lock and leaves monitoring alone. Failed cancellation
triggers restoration. Lost responses require readback, never a repeated start.

After handoff, PPS-first monitoring has no timing-quality shutdown deadline.
Systemd service failure invokes the staged recovery worker; an explicit operator
recovery uses the same path. A clean external service stop does not invoke
`OnFailure`. Warm restart is unsupported: leave timeservice disabled at boot,
timesyncd enabled but stopped during this run, and leap-fetch disabled.
Final synchronized workstation/mDNS acceptance and boot persistence remain pending.

Statistics are checked each monitor interval: at most 128 regular named entries
and 8 MiB of unique inode data; hardlinked current/dated pairs count once. An
8 MiB per-file limit also applies to the service. These are fault bounds, not a
disk quota or log-rotation policy. Exceeding a bound triggers recovery. Keep
up to 60 numbered captures of durable monitor state at the 30/300-second cadence;
exhausting that retrieval budget does not stop the service. Dual-stack readback
returns stored state, not a new sample, and never accepts timing.

Recovery stops the pair, preserves terminal monitor/statistics evidence, restores
files/UART and the baseline clock service, then checks continuity. Conditional
transient cleanup requires a matching recovered receipt and idle workers. Held
recovery requires a new review. Preserve the original v6 held state and all
source stages. Subsequent readback/recovery uses sealed helpers even if repository
files change; a new start still requires unchanged current inputs. Start before
the review's installation cutoff; monitoring and recovery of that started
operation do not expire with its start window.

### Local packet-buffer qualification

The collector candidate requests 2 MiB and records libpcap version, actual
packet-socket backend and libpcap packet timestamps. Existing packet/time bounds
and drop rejection remain unchanged. The opt-in real Linux fixture is
`tests/test_runtime_capture_linux.py`; it refuses a namespace with interfaces
other than loopback before creating its isolated veth pair. Invoke it with
`podman unshare unshare --net`, an explicit private output directory and an
available libpcap library. It does not install packages or contact a target.

Three spaced-traffic and three burst comparisons for each of IPv4 and IPv6,
using Debian libpcap 1.10.5-2 on x86-64 WSL2, confirmed TPACKET_V3. The 256 KiB
control dropped packets in all twelve cases; the 2 MiB candidate captured all
2880 expected packets with matching identifiers and zero drops. These local results do not qualify the Raspberry Pi
kernel/architecture. Retain target backend and counters in the next approved
capture; packet timestamps use the local clock and do not automatically establish
RTT across clock adjustments. Mocked unit tests remain separate from this real
socket/kernel fixture, which is not run by ordinary unprivileged CI.

### Bounded NTS/PPS runtime diagnostic

The [v5 diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v5/review.md)
was executed once and recovered. Its adjacent terminal receipt records matching
IPv4/IPv6 recovered state from readback attempt 1; cleanup completed. Diagnostic
and time-service acceptance remain false. Preserve the archive, rejecting sample,
journal, statistics, receipts and backups; do not replay its start.

The short serial/PPS gate passed and PPS was selected in the first startup
sample. The first diagnostic sample failed journal health because control-key
reading and one-key-added messages at priority 3 were unclassified. Promotion
commands remained empty, so this trial did not add selectable NMEA or the three
NTS upstreams. It provides no settled timing or NTS packet acceptance. The 2 MiB
observer reported TPACKET_V3 with zero packets and zero drops before recovery;
this does not qualify the buffer under traffic.

The corrected classifier requires exactly one ordered control-key read/add pair
when PPS startup is enabled: the fixed per-start key path, one added key, current
daemon provenance and a 120-second apply-time window. That window does not move
when NTS promotion begins. Other key-loading messages remain errors. Retained
v5 journal replay and regression tests pass offline, including missing,
duplicate, reordered, late, altered and wrong-origin records. This allowance
does not establish timing, promotion or NTS authentication.

The [v6 diagnostic review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v6/review.md)
was executed once. Serial/PPS functionality and journal classification passed;
cold-start frequency initialization was recorded. Thirty samples were retained,
but three qualifying fresh PPS updates were not established and no promotion
commands were submitted. A subsequent measurement failed. Automatic restoration
reached `recovery_held` on `package/service/Python/process drift`.

Readback attempt 13 returned matching held state over IPv4 and IPv6, following a
sample-update mismatch in attempt 12. The original v6 has no recovered terminal
receipt; its held state and source stage remain preserved. Restoration was later
accepted under the separate continuation below. Source cleanup remains unapproved.
Do not repeat start or force recovery through an unidentified continuity mismatch.
At the subsequent inspection, the independent timer was active/waiting with no
recorded trigger and its recovery service inactive. At the later restoration
continuation, the timer was absent/inactive and its recovery service failed.

The [sealed recovery inspection](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-recovery-inspection-20261013-v1/review.md)
completed one capture against v6's exact archive and matching held readback attempt
13. Readback attempt 2 agreed over both endpoints, and diagnostic closure completed.
Attempt 1 was blocked locally before connection. The journal confirms the PPS
qualification deadline terminated ntpd before promotion. Continuity differs in
the historical boot ID, SSH/NetworkManager PIDs and failed timeservice state;
inventory, Python metadata and active-daemon observations match. Bootstrap
timesyncd and Avahi were active; timeservice's unit and `/etc/ntp.conf` were absent.
Retrieval acceptance does not accept restoration or authorize source cleanup.

Offline replay of the exact frozen checker establishes that it already permits the
boot/PID differences. Only timeservice's failed state prevents the comparison from
passing. Keep that checker and all historical baselines unchanged.

The [restoration continuation](/home/aaron/code/.local-evidence/homelab-ntp/current/cutover-restoration-20261014-v1/review.md)
was executed once and accepted: all ten restoration checks passed, readback attempt
1 matched over IPv4 and IPv6, and conditional closure completed. The only mutation
was the guarded timeservice failure reset. The retry timer was already absent and
inactive, so no stop was issued; its failed recovery service record was retained.
The original v6 held state and all evidence remain untouched. Use the continuation's
separate acceptance receipt and matching readback/closure as restoration evidence;
this does not accept timing, activate service or authorize source cleanup.

`run-cutover-restoration.py seal` binds the executed source archive, accepted
inspection archive, both submitted readbacks and diagnostic closure. Its independent
restoration window does not renew a failed trial or accept a new installation.

One protected continuation verifies source identity/members and already-restored
files, directories and UART settings under the original exclusive nonblocking lock.
It compares current observations with inspected state, checks the exact retry timer
and idle recovery worker, stops that timer, and rechecks for a queued worker. It
conditionally resets only an unloaded, PID-zero failed timeservice, then requires
inactive/dead. The unchanged reboot-aware checker validates continuity and network;
current accounts, loader cache and hardware metadata must match accepted records.
All checks run against a private copy of original inputs; source state and evidence
remain unchanged. No daemon start, clock adjustment, configuration/receiver write,
reboot or NTS traffic is included. Network acceptance includes original gateway and
dual-stack egress probes.

The worker is bounded to 180 seconds. Unexpected state holds; timer stop or failure
reset already performed remain in place. Do not rearm the old recovery or repeat
start. Up to three numbered readbacks retrieve one stored terminal report over both
endpoints; matching readbacks accept restoration only. Conditional closure retains
all stages/evidence and performs no source cleanup. Resolve any hold under a new
review before another trial. PPS qualification policy remains separately unresolved.

Use `run-cutover-inspection.py seal --recovery-held --source-attempt N` with the
executed archive digest and retained matching readbacks. The mode copies bounded
original command/recovery records and statistics; retrieves boot/time-bounded
operation journals; inspects fixed service/recovery-timer properties; and runs the
pinned original read-only package/service/process/Python observer. Compare against
the original baseline without rejecting a diagnostic merely because it differs.

A shared nonblocking source lock protects collection. Only recovery-owned state
fields may have changed since the held readback; current phase must be held or
recovered. Verify original runtime-check baseline/observer bytes, and compare saved
records/statistics again at closure. Missing, oversized, changed or incomplete
evidence holds retrieval acceptance and preserves partial results. Conditional
dual-stack readback retrieves the same stored report; cleanup records diagnostic
closure without changing the source stage or any service/timer.

Inspection acceptance is never restoration or timing acceptance. Resolve the
continuity mismatch and confirm recovery through a separately approved stage
before another trial. Warm-restart policy and persistent service cutover remain
pending.

The [sealed runtime review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v3/review.md)
was executed once and recovered, with matching dual-stack readback and cleanup.
Its saved rejecting sample identified a changed Cloudflare address outside the
sealed scope; its journal was retrieved successfully. Diagnostic acceptance
remains false. Do not replay it. Use the existing
`run-service-cutover.py seal --diagnostic` path with the accepted receiver,
network and latest recovered-transaction directories plus `--retained-dir` and its exact
`--retained-sha256`. The checked-in `runtime-diagnostic-recipe.json` and current
input hashes define the scope; do not reuse a historical executable bundle.
V4 completed recovery, dual-stack readback and cleanup with partial diagnostic
evidence; see HISTORY. A successor binds that recovery and the original accepted
retained proof by its immutable member hash.

The [v4 review](/home/aaron/code/.local-evidence/homelab-ntp/current/nts-pps-runtime-20261013-v4/review.md)
completed its observation and mandatory recovery. Terminal dual-stack readback
was attempt 11; cleanup is complete. NTS authentication passed in the trial, but
PPS timing failed and capture drops withheld diagnostic acceptance. Preserve all
nonterminal readbacks. A successor must resolve the terminal attempt from its
matching receipt, not assume attempt 1 or relabel earlier evidence. Its candidate source
restriction is `nomodify noquery`, without `notrust`: pinned 1.2.5 processes the
legacy MAC requirement before NTS response validation. Every upstream still
requires `nts`; Default LAN serving and localhost administration are unchanged.
Test the full restriction set and upstream options before sealing. Packet
authentication and settled timing remain live acceptance requirements.

The four-address capture scope is exactly the union of upstream addresses in the
original accepted retained proof and the latest recovered measurement. Bind both
to the target and immutable receipts; reject unobserved additions, duplicates,
non-public addresses or more than four entries. Both observed Cloudflare
addresses are included. Do not dynamically expand capture. V3's reported loss
remains unexplained and v4 also reported capture drops; either drop counter
still prevents complete evidence. Review retained observer and timing statistics
before preparing another trial. Do not infer network loss from observer drops.
Preparation does not authorize another activation.

Retained v4 analysis is complete; see HISTORY and its private report. Clockstats
show complete SHM2 ingestion, while startup loopstats show cold frequency
initialization after an uncalibrated NMEA correction. Peer jitter during that
transition must not be labeled pulse-edge jitter or used to calibrate serial
time. Do not reuse the startup frequency estimate as a drift seed.

The larger-buffer candidate has passed the local fixture above; target capture
acceptance remains pending. The cold-start promotion path above has passed local pinned-version tests. Use measured
calibration and timing milestones within hard recovery bounds rather than
treating elapsed startup time as convergence.

This profile installs the candidate helpers and starts PPS alone, then promotes
selectable NMEA and three NTS associations after qualification. The rendered
supervisor unit uses `Restart=no`. It always restores files, service state and
UART settings; `accept` and manual `probe` modes are rejected. It never enables
the service or leap timer, and performs no workstation or firewall probes.
Clock corrections made during the trial cannot be undone by file recovery.

Before activation, verify libpcap availability and a ready non-promiscuous eth0
observer. The retained package list includes libpcap; no package install is in
scope. Kernel filtering restricts collection to UDP 123 and the four evidence-bound
upstream IPs. Save only selected NTP/IP/UDP headers, not payload or NTS cookies.
Cap collection at 512 packets/1620 seconds, backed by a 1640-second service limit;
unsupported or incomplete headers, capacity exhaustion and reported drops mark
packet evidence incomplete. An unexpected DNS-selected address ends the trial
rather than expanding the approved capture scope. Pending NTS associations
without an address have a 60-second setup grace, checked at each 30-second
sample; they cannot count toward acceptance. Save rejecting measurements before
ancillary queries or recovery. Capture a boot-bound journal cursor before
activation and query after it with bounded fields/output. Retain monotonic and
boot checks; journal failure must not block restoration. The observation point cannot
by itself locate a network drop or prove remote receipt/authentication.

The existing short matched GPSD/SHM gate and early localhost NTP response remain
mandatory, now with complete NTS/system counters. Only then launch autonomous
sampling: at least 30 seconds between samples, at most 50 samples and 1500 seconds
after apply. Record NTS send/good/bad counters, packet-processing counters,
per-peer sent/received/reach/flash/srcadr/dstadr/refid, frequency, offset/jitter,
addresses/routes and journal health. Counter resets, observer loss, changed
upstream scope or daemon/journal safety failures recover immediately. Retain
ordinary NTS reach and timing failures as diagnostic observations.

Timing success requires completed bootstrap and promotion, including distinct
PPS updates, unchanged 5 ms offset/1 ms jitter and authenticated/reachable NTS gates. Three
consecutive passing samples may finish early; otherwise stop at the bound.
This window is not proof of convergence or permission to relax acceptance.
The observation worker has a 1620-second limit, a 240-second stop/recovery
allowance and an unconditional recovery ExecStopPost; the independent 1800-second timer remains armed. Every outcome
restores the baseline, including successful collection. Recovery preserves
statistics and packet evidence; evidence gaps do not become successful checks.
Terminal readback also includes before/after addresses/routes and one bounded
boot/monotonic-filtered service/worker journal (under 2000 records and 2 MiB).
Missing or truncated evidence holds diagnostic acceptance without preventing
restoration; preserve the original failure when evidence retrieval also fails.
Recovery uses its own bounded command journal; observation log exhaustion must
not prevent restoration commands. Preserve both logs in the private stage.

Use one `execute --mode start`; do not replay it after uncertainty. Conditional
numbered readbacks retrieve all samples and terminal packet/statistics evidence.
If needed use the one explicit recovery, then require matching dual-stack
recovered receipts before cleanup. A complete diagnostic receipt also needs
bounded completed observation, no diagnostic error, complete packet evidence
and retained statistics. It always records time-service acceptance as false.
Cleanup retains original and diagnostic stages and verifies transient units
have stopped. No automatic recovery is promised across reboot.

`run-nts-transport-inspection.py` seals the checked-in recipe, helpers, tests,
governing documents and the network owner's `UNIFI_ACCESS.md`, bound to the
original recovered cutover specification and live-revalidated boot/state. The
controller step verifies DNS/TLS before retrieving the Doppler credential in
memory. The operator confirms it has read/write capability; this inspection's
code enforces GET-only scope. GET-only collection covers site/network/zone identity,
policies, Default LAN-zone/External-zone ordering in both directions and referenced
matching lists. The observed ordering schema separates user rules before/after
system-defined rules; retain system policies and their indices as well. Limits:
40 requests, 400 rows per endpoint, 16 referenced lists, 2 MiB per response,
16 MiB total and 300 seconds. API/identity/schema failures hold the stage.
Secrets and raw authentication output are never written to evidence or Git.

Only a successful bound controller capture permits the node step. One protected
capture resolves the three approved names, records address/route selections,
and tries at most one public address per name/family from root and the NTP
account: at most 12 TCP 4460 connections, two seconds each. No TLS handshake,
NTS cookies, UDP probe, daemon start, receiver write or clock change occurs.
Account-context probes do not reproduce systemd/ntpd sandboxing. Both management
readbacks must match before diagnostic closure; preserve prior and new evidence.
Failed connections are valid diagnostic observations, not time-service acceptance.
The API snapshot is not atomic and does not prove a rule hit. Controller traffic
logs/counters remain unknown unless returned in the approved policy metadata.

For a fresh approved bundle, execute the controller using `--mode unifi`,
then `--mode start`, `--mode readback --attempt 1` and `--mode cleanup`. Never
repeat a registered collection after lost output. The recipe does not authorize
gateway SSH, cloud access, alternate APIs or firewall changes. Historical
September 21 controller evidence informed schema tests only; current facts must
come from the accepted October 13 capture. Do not replay its registered modes.

Evidence: pinned NTPsec 1.2.5
[`check_minsane()`](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/ntpd/ntpd.c),
[survivor selection](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/ntpd/ntp_proto.c)
and [`tos` documentation](https://gitlab.com/ntpsec/ntpsec/-/blob/42b5703303c8c7e6513f3a119cfab670924dd7be/docs/miscopt.adoc).
Source inspection used the retained local pinned release; current upstream
documentation was checked as corroboration. Current target evidence remains
required for a future cutover.

For a newly sealed and separately approved stage, use the controller's
`execute` command with its exact archive/hash and `--mode start`. One start
is allowed. The controller registers submissions before transport and retains
stdout/stderr/status; lost responses require conditional readback, never a
repeated start.

The trial backs up and replaces the supervisor, pairing helper, NTP/supervisor
configuration, systemd unit and Avahi configuration. It creates a root-owned
leap directory, ntp-owned drift/statistics directories and reviewed leap
maintenance unit/timer. The initial leap asset is the byte-exact accepted
distribution file under `configs/leap-seconds.list`, internally checksummed
and valid through June 28, 2027 UTC; this does not imply a publisher signature.
Avahi is limited to eth0, IPv4/IPv6 enabled, no reflection or wide-area discovery.
NTPsec advertises with `-m`; the candidate retains outbound global IPv6 for NTS
while unsolicited client service is limited by the configured restrictions.

Arm independent 1800-second recovery before mutation. Apply has a 120-second
systemd lifetime limit and failure recovery. Stop bootstrap timesyncd only
at the reviewed cutover, then start the pair. `timeservice.py` runs the shared
`gpsd-pairing.py` gate before every ntpd launch: at most 15 seconds for the GPSD
socket, then 30 seconds to match five leap-0 timestamps from each expected
device/unit. Stop and reap both diagnostic monitors before starting ntpd;
missing or changed pairing stops the pair. The start response exposes the
gate and early localhost ntpd query result before longer observation.

Use numbered `--mode probe --attempt N` calls, at least 30 seconds apart,
up to 40. Three consecutive successful probes are required: leap 0, stratum 1,
PPS selected/reachable, serial reachable, absolute PPS offset at most 5 ms and jitter at most 1 ms,
all three NTS associations authenticated/reachable with cookies, unchanged
supervisor, expected daemon credentials and no timeservice/Avahi error-priority
journal entries. These initial service thresholds do not prove UTC accuracy,
long-term stability or holdover. Retain the measurements for later Phase 3A work.

`--mode accept` first reads both management endpoints and tests this workstation's
IPv4/IPv6 NTP responses, denied external mode-6 queries and `_ntp._udp.local`
SRV port 123 plus the target's fixed A/AAAA records. Multicast reachability is
unverified until this approved stage; any missing client proof blocks acceptance.
The target then rechecks protected inputs and native/package/account/loader/
boot/network/hardware continuity and current convergence with recovery time
remaining. Only then enable timeservice, disable timesyncd, enable/start leap
maintenance, record durable acceptance and cancel recovery. The four-week timer
uses `OnActiveSec=15min` and up to 30 minutes random delay for its first check;
its root-owned temporary file, IANA HTTPS source and bounded retry command
are rendered in `templates/ntpleapfetch-j2.service`. No ntpd restart is configured.
A post-acceptance leap maintenance fetch is part of the reviewed scope.

Use numbered `--mode readback --attempt N` for uncertain or terminal state
through both endpoints (up to 60, at least 30 seconds apart). A matching
accepted/recovered receipt permits `--mode cleanup`. One explicit `--mode recover`
is available in addition to independent timed/failure recovery. Recovery stops
the pair and maintenance, restores exact backups and UART settings, preserves
bounded generated statistics, restarts Avahi/bootstrap timesyncd and verifies
original continuity. Unexplained drift holds recovery for inspection. Retain all
stages and SHM segments. Cleanup clears transient controls only after terminal
acceptance/recovery; it leaves an accepted service running. No reboot is included,
and this recovery does not survive reboot or undo clock corrections.

## Current state and remaining work

j2-svntp1 is the renamed former j1-svntp1 physical node, now running Raspberry
Pi OS Lite Trixie on the spare card. Its accepted foundation contains 686 package
records. The retained NTPsec/GPSD source candidate has 159 manifest entries;
both upstream suites, native staging and mDNS feature acceptance passed.
The 159 native file/link entries are installed and accepted; runtime
configuration and activation remain pending.

| Stage | State | Next requirement |
| --- | --- | --- |
| Media and bootstrap | Accepted | Preserve original Debian 11 card and primary/antenna power |
| Foundation | Original foundation, pps-tools, bc and seven mDNS prerequisites accepted; 686 package records; installation control cleanup complete | Preserve accepted inventory and recheck it before further live changes |
| Source candidate | New mDNS-enabled GPSD/NTPsec candidate accepted; 159 manifest entries; v5 evidence preserved | Preserve accepted build and installation receipts |
| Live installation | Native installation, terminal readback and payload cleanup accepted; copied_not_activated | Preserve native installation receipt and retained root journal |
| Runtime configuration | Hardware continuation, account/runtime v2, explicit-PPS pairing and receiver/runtime-input inspection accepted; cleanup complete; original evidence preserved | Runtime diagnostic v4 recovered; terminal attempt 11 and cleanup retained; PPS timing and capture completeness unaccepted. Cold-start promotion and larger buffering tested locally. V5 recovered on unclassified control-key journal messages before promotion; dual-stack readback and cleanup complete. V6 journal gate passed, but restoration is held on continuity drift; readback 13 matches on both endpoints. Source cleanup blocked; diagnostic inspection and closure complete. PPS deadline confirmed; historical boot/PID baseline and failed timeservice state differ. Timer was waiting at capture; later outcome unknown. Frozen-checker replay isolates failed timeservice state; guarded reset executed; restoration continuation accepted through both endpoints and closed. Old timer already absent/inactive; historical v6 held state and evidence preserved. Offline PPS replay complete: three passing updates did not fit the retained trajectory before the bootstrap deadline. Continuous PPS-first monitoring and terminal retention implemented/tested locally; start-and-monitor v1 stopped in preflight on expired nested hardware acceptance; conditional readback found no operation state; partial stage retained. Read-only hardware/runtime revalidation v1 held on runtime binding; matching dual-stack readback and diagnostic closure complete; revalidation v2 prerequisites accepted through both endpoints; diagnostic closure complete; monitor v2 startup/early/workstation checks passed; handoff rejected historical boot-ID comparison; dual-stack recovery and transient cleanup complete; handoff continuity corrected/tested offline; read-only revalidation v3 accepted against recovered monitor v2 through both endpoints; diagnostic closure complete; monitor v3 startup and workstation structural checks passed; handoff rejected PPS platform/class cardinality; approved recovery matched through both endpoints and transient cleanup completed; PPS checker corrected and real transition tested offline; remaining historical executable dependencies must be migrated before another activation review; successor recovery tested past historical expiry. Monitor v3 recovered after the PPS hardware handoff check failed; any successor needs a fresh sealed review and separate execution approval. Persistent warm-restart policy and timing acceptance remain pending. |
| Maintenance/reporting | Policy installed; other assets are templates | Leapfile command/reload review, cron/relay rendering and delivery acceptance |
| Node/network acceptance | Fixed dual-stack networking and native/service continuity accepted after recovery reboot | Fresh hardware/time acceptance, dual-stack NTP clients and monitoring remain pending |

On October 12, the earlier v2 foundation snapshot passed validation with the same
679 package records, 197 protected inputs and eight configuration directories.
Its root-owned capture stage was cleaned up. The subsequent mDNS requirement
changed the foundation recipe, requiring a new hash-bound capture before metadata
resolution. The v2 capture authorizes no package changes and cannot bind
the revised recipe.
The exact snapshot hash and retained execution outcome are recorded in HISTORY.

The [v3 capture review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-preflight-20261012-v3/review.md)
was approved and executed once against the revised recipe and pinned manifest.
Identity checks, terminal readback and full snapshot validation passed;
the verified root-owned stage was removed. The accepted snapshot retains 679
package records, 197 protected inputs and eight configuration directories.
Its hash and receipts are recorded in HISTORY. The
[corrected snapshot-bound resolution review](/home/aaron/code/.local-evidence/homelab-ntp/current/fresh-foundation-resolution-20261012-v4/review.md)
was approved and executed once. Terminal readback passed the complete resolution
validator: signed metadata, dependency closure, exact native/Python simulation
agreement and full target continuity. Verified workspace/stage cleanup completed.
The accepted delta is seven additions, with no upgrades or removals. HISTORY
records the bundle/report hashes and receipts. The
[seven-package installation review](/home/aaron/code/.local-evidence/homelab-ntp/current/foundation-mdns-install-20261012-v1/review.md)
was approved and executed once. Exact package, dpkg, protected-input, hook,
needrestart and boot/access/network acceptance passed. Controls and the original
automatic-update disposition were restored. The accepted inventory is now
686 records and is mirrored in accepted-packages.tsv from hash-verified terminal
evidence. The old 679-record snapshot/resolution remain executed preparation
records; their baseline no longer describes the target after installation.

The installation review includes the Avahi libraries' ldconfig triggers and
libdbus-1-dev's generated XML catalog maintenance. Successful cleanup restores
temporary controls and the original automatic-update disposition; it retains
the executed privileged stage, claim, backups and logs as recovery evidence.
At the package-installation gate no source build or mDNS runtime activation
had occurred. The subsequent source build was separately approved and accepted
against this inventory; runtime activation remains pending.

Resolution v3 performed its isolated refresh and simulation but final continuity
was held: the resolver left its temporary APT_CONFIG in the worker environment.
Terminal readback and verified workspace/stage cleanup completed. The resolver
now restores the caller's environment on exit; protected collection still rejects
unexpected overrides. The held report is retained evidence, not an accepted
installation input. Accepted v4 supplies the current preparation evidence.

There is no completed unattended end-to-end installer yet. Foundation preparation
now uses a checked-in recipe, fresh target snapshot and accepted combined
resolution report; it reads no historical bundle or acceptance receipt.
Source preparation now renders the target identity, pinned SSH binding and
exclusive stage from evidence and a required operation ID, and binds the
accepted foundation boot. The [mDNS build review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-build-mdns-20261012-v1/review.md)
was approved and executed once on j2-svntp1. Both upstream suites, native staging,
u-blox/features, imports/linkage and explicit NTPsec mDNS acceptance passed;
the accepted release manifest is mirrored byte-for-byte in the repository.
The package inventory and boot/access-service continuity remained unchanged.
Conditional readback was unnecessary; complete terminal evidence was retained.
Live installation/runtime profiles and
hardware/network acceptance remain pending.

## Repository assets and private evidence

| Asset | Purpose |
| --- | --- |
| [source-build-recipe.json](../configs/source-build-recipe.json) | Source revisions, archive integrity, build roots/options, prefix and jobs |
| [foundation-recipe.json](../configs/foundation-recipe.json) | Fresh foundation requirements, observation coverage, package effects, acceptance and recovery |
| [runtime-discovery-recipe.json](../configs/runtime-discovery-recipe.json) | Fixed read-only runtime queries, bounded configuration/device inputs and configuration requirements |
| [installation-assets.json](../configs/installation-assets.json) | Exact image/source/package download URLs, sizes, hashes and source signing keys |
| [public-keys](../configs/public-keys) | Public source verification keyrings; no private keys |
| [accepted-source-release.json](../configs/accepted-source-release.json) | Byte-exact accepted target candidate file/link manifest |
| [accepted-packages.tsv](../configs/accepted-packages.tsv) | Accepted target package/version/status reference, not a future observation |
| [asset-provenance.json](../configs/asset-provenance.json) | Vendored reporting-script identity and template adaptations |
| [scripts](../scripts) | Maintained inspectors, preparation, guarded installers and runtime helpers |
| [templates](../templates) | Service/policy artifacts and examples requiring reviewed target values |
| [tests](../tests) | Offline success/rejection, preservation, parser and lifecycle regressions |

Required reusable assets belong in this repo. Large publisher binaries are
obtained through the checked-in verification tool, not copied repeatedly into
operation folders. Keep credentials, raw host captures, recovery-card data and
execution receipts private. The historical private index is
`/home/aaron/code/.local-evidence/homelab-ntp/current/catalog.json`; it identifies
the earlier October 10 package/Python/source records by hash and provenance;
it is not the current mDNS build inventory or an executable installation input.
The current accepted target files remain under ama's retained
`.ntp-source-build-mdns-20261012-v1/candidate/stage`. The earlier v5 workspace
is preserved as prior executed evidence.

The shared `.local-evidence` directory also serves other projects. NTP cleanup
does not authorize deleting those projects' records. Retain unique observations
and accepted provenance until their purpose/dependencies have been checked.
Do not keep unsuccessful attempts as separate operating instructions. Preserve
useful corrections in current code/tests and this recipe instead.

Accepted continuation helpers and their regressions remain recovery assets;
they do not authorize replaying a consumed operation. Private cleanup/retirement
records identify the explicitly approved removals. A temporary consolidation
checkpoint preserves original prose for review; it is not another active recipe.

## Fetch and verify installation inputs

The pinned image is Raspberry Pi OS Lite arm64 Trixie, October 6, 2026:
compressed size 550466056, expanded size 3078619136. Both integrity values are
in the installation manifest. This is an exact selected image, not a claim
about the latest publisher release. Use the architecture's confirmed Pi 4,
spare-media, original-card and independent-access requirements before writing.
Imager completion/verification evidence does not establish Wi-Fi state or
individual account settings; verify those after boot.

From the repository root, choose only needed groups and a new private cache:

```bash
python3 -I -B ntpsec/scripts/fetch-installation-assets.py \
    --cache "$new_cache" --group image --group foundation --group sources
python3 -I -B ntpsec/scripts/fetch-installation-assets.py \
    --cache "$new_cache" --group image --group foundation --group sources --verify-only
```

Other manifest groups are mail, hardware, munin and watchdog. Fetching them
does not approve installing or activating them. The tool validates all inputs
before cache creation, rejects unsafe paths/URLs and conflicting application
packages, verifies exact size/hash, publishes only complete files, refuses
replacement and checks both source signatures using pinned public keyrings.
It executes no downloaded script or package. Source/key changes need review.

Debian archive hashes were obtained from previously accepted signed Release
metadata and matching Packages records, not inferred from filename/version.
The manifest binds that evidence's integrity identity. Downloads are verified
against the checked-in pins; this does not replace fresh APT dependency,
origin, policy/hook and installed-state checks before mutation. If an exact
asset is unavailable, stop; do not silently substitute a newer version.

## Observe the target before rendering

Use a separately authorized, hash-bound read-only scope. Pin the target's SSH
key, preserve existing access and capture complete stdout/stderr/terminal status
once. Never retry a potentially submitted operation to recover missing output.

| Helper | Contract |
| --- | --- |
| inspect-node.sh | Debian 11/root legacy baseline; fixed local commands and byte-exact captures; missing tools or protected drift remain gaps |
| inspect-trixie.py --inspect | Non-root Debian 13/aarch64 identity, packages, sources, network/storage/services and passive hardware metadata |
| inspect-trixie.py --package-policy | Installed package/source/update/needrestart policy observations |
| inspect-trixie.py --installation-inputs | Read-only inputs for package preparation; no refresh/install |
| inspect-trixie.py --keyring-hooks | Installed authentication and hook source evidence |
| pre-rebuild-health.sh / inspect-ipv6-time.sh | Scoped health/protocol diagnostics; explicit target/client boundary |
| hook-closure-preflight.py / read-debconf-answers.py | Bounded hook/database observations before approving package effects |

Inspectors do not authorize service activation, Wi-Fi disablement, sensors/I2C
transactions, GPS/PPS/RTC access, controller mutation or stress testing.
Recorded source hints and conditional boot snippets are not effective policy.
Do not source captured configurations, execute them or publish raw secrets.

The current rebuilt node was observed at DHCP IPv4 10.1.0.137; that is not its
future fixed service address. Python was observed as 3.13.5 with purelib
`/usr/local/lib/python3.13/dist-packages` and extension suffix
`.cpython-313-aarch64-linux-gnu.so`. New target observations must establish
their own interpreter/ABI, package paths, manager/profile, resolver, accounts,
device ownership, boot configuration and recovery access.

## Package foundation and installation controls

The source recipe includes build-essential, bison, m4, pkg-config, python3-dev,
scons, libssl-dev, libcap-dev, libseccomp-dev, libncurses-dev, asciidoctor,
python3-serial, pps-tools, bc, libavahi-compat-libdnssd-dev and avahi-daemon.
The mDNS headers/library use Avahi's DNS-SD compatibility API; Avahi supplies
the runtime responder. The original deployment added 46 packages;
the fresh preparation manifest now pins 56 requirements, including the two
prerequisite roots supplied by that image's baseline. `build-essential` is pinned
directly; the explicit `root_providers` mapping selects Trixie's `pkgconf` for
the `pkg-config` capability. Additions are calculated from the fresh snapshot.
The installation manifest holds each exact version/architecture/size/hash.
python3-dev replaces the old python-dev name. Git is not needed for these
publisher-archive builds. Target client/manual builds need their target
ncurses/AsciiDoctor dependencies even if those tools exist on the workstation.

pps-tools supplies `/usr/include/sys/timepps.h` for magic_hat/PPS builds and
later diagnostics. bc is required by unchanged upstream regression timing.
Do not use a private header as a substitute for the installed dependency.
Never install APT ntp, ntpsec, gpsd, gpsd-clients or python3-gps, create a global
python alias, use unreviewed pip or purge/autoremove packages as a shortcut.

Resolution uses resolve-trixie-packages.py and its guarded transport helpers.
An isolated metadata refresh uses fresh snapshot-bound source/key/hook inputs and a private
APT list/cache workspace; it is a distinct approved mutation scope. Require
signature/index/package identity, complete recommendations/dependency closure,
exact native simulation semantics, unchanged inventory and clean dpkg. No
moving suite, arbitrary source or changed existing package is implicitly allowed.

Before installation, inspect apt-listchanges, Debconf backend/answers,
needrestart hooks and package maintainer/config/trigger scripts. Hook wrappers
may tolerate failures and APT success alone is insufficient. Explicitly bound
controls suppress transaction-time mail/restarts, preserve effective policy and
restore automatic-update disposition. Account/device/service effects remain
reviewed package effects. Reject unreviewed update-menus execution.

The preparer takes both hook/answer helpers and the temporary
apt-listchanges-transaction.conf policy from this repo. The
[foundation recipe](../configs/foundation-recipe.json) declares requirements,
protected observation coverage, package effects, acceptance and recovery.

prepare-foundation.py prepares a foundation from fresh evidence and verified
cached assets. foundation-install.py and run-foundation-install.py enforce exact
inputs, exclusive claim, pre-state and recovery/cleanup. Historical supplements
remain consumed execution records; they are not preparation inputs.

Fresh preparation follows this sequence:

1. Review the recipe and pinned manifest for the selected image. Fetch/verify
   the foundation group using the checked-in assets tool. Preparation itself
   performs no network access.
2. Separately approve root-owned staging and one read-only snapshot capture.
   capture-foundation-snapshot.py and its peer worker/inspection/hook/answer
   modules must be staged as protected root-owned files. Do not invoke the
   collector as root from the user-owned repository. Bind the recipe hash,
   observed hostname/kernel, SSH endpoint and controller epoch. The collector
   reads the normal Debconf database's five approved answers; it never reads
   the password database. Retain complete output/status and review the snapshot.
3. Resolve one combined foundation group using the recipe's roots, freshly
   authenticated metadata and native simulation. The resolver specification
   must bind hostname, kernel, snapshot_sha256 and the snapshot's protected
   input state. Review origins, dependency closure, recommendations, hooks and
   continuity before accepting its report. A pinned-version conflict requires
   a reviewed recipe/manifest correction; never silently upgrade or substitute.
4. Wrap the unchanged accepted report in resolution.json with schema=1,
   snapshot_sha256, asset_manifest_sha256 and report. Hash-bind both evidence
   files in the offline preparation command below.

Use `run-foundation-preflight.py seal` to prepare the capture bundle from repository
inputs, a pinned `known_hosts`, target identity and a unique operation ID. Its
private output contains the complete review, member manifest and archive hash.
The archive retains the current installation-assets manifest controller-side;
its hash is also bound in the operation specification. Sealing validates the
recipe's pinned requirements offline and does not fetch packages or metadata.
Snapshot staging/collection still uses only the reviewed collector inputs.
After hash-bound approval, `execute --mode collect` creates an exclusive root-owned
stage and collects once. `--mode readback` retrieves the same terminal snapshot;
the checked-in validator must pass before accepting it. `--mode cleanup` requires
retained terminal readback and removes only the verified stage. Keep complete
controller output and the accepted snapshot after cleanup. Busy, incomplete or
drifted staging is preserved for reviewed recovery; never replay collection.
No temporary sudoers fragment is needed with the existing operator-managed sudo.
For helper observations through `/bin` or `/sbin`, validate the root-owned
merged-/usr link and its exact `/usr/bin` or `/usr/sbin` destination, then check
the protected canonical file or its absence. Preserve the requested path in the
snapshot; repeat these checks during installation. Other directory symlinks and
changed alias targets remain rejected.
Resolution is a subsequent sealed operation bound to the accepted snapshot hash;
capture approval does not authorize metadata refresh or package installation.

Use `run-foundation-preflight.py seal-resolution --snapshot PATH
--snapshot-sha256 SHA256 --known-hosts PATH --operation-id ID --output PATH`
to prepare that operation without target contact. The checked-in
`foundation-resolution-policy.json` defines trusted release identities and
verification packages. The tool derives native/foreign architecture, exact root
pins/providers, installed versions, protected inputs and configuration memberships
from the fresh snapshot and repository assets. It reads no historical bundle or
baseline. Execution uses the same one-shot collect/readback/cleanup protocol.
It rechecks the full snapshot before and after isolated APT refresh and one native
simulation; the complete dependency/delta validator must pass after readback.
Live APT lists, packages, policies and automatic-update units stay untouched.
Cleanup removes the exclusive disposable metadata workspace after ownership and
inode checks; signed releases, selected Packages records and complete query output
remain in the controller's private resolution wrapper. A held or interrupted
operation is never replayed.

The snapshot contract is schema=1, recipe_sha256 and collected_epoch; observed
hostname/kernel/boot_id/os/architecture/machine/caller/ssh; complete baseline
package/version/status mapping; inputs with path/hash/owner/group/mode or explicit
absence; directory membership and discovered Debconf/listchanges/keyring/source coverage;
five answers plus their static database structure; foreign architectures,
network and automatic-update state; empty dpkg audit and no active time daemons.
The recipe defines required observations. Source/key/hook snippets alone are
insufficient. The collector rechecks packages, files, directory membership,
boot, network and update state before returning.

```bash
python3 -I -B ntpsec/scripts/prepare-foundation.py \
    --snapshot "$snapshot" --snapshot-sha256 "$snapshot_sha" \
    --resolution "$resolution" --resolution-sha256 "$resolution_sha" \
    --asset-cache "$verified_cache" --known-hosts "$pinned_known_hosts" \
    --operation-id "$new_operation_id" --output "$new_preparation"
```

The preparer computes missing packages from exact pinned requirements and the
observed inventory, including Multi-Arch names from matching Packages/archive
control metadata. It rejects existing-version/status conflicts, incomplete
closure, unexpected native deltas, cache drift, unsafe paths and stale snapshots
before creating output. Expected inventory is the exact baseline plus that delta;
there is no fixed baseline or addition count. Already satisfied prerequisites
stay untouched. Zero additions produce no APT install call; any policy application
still requires a reviewed execution bundle and approval.

The rendered worker/launcher bind the snapshot's hostname, endpoint/key, kernel,
boot and unique stage. They recheck package/input/network/update state before
controls or unpacking. Preparation includes recipe, pins, snapshot, resolution,
provenance, member hashes and standalone regressions. Add the exact review, run
the sealed tests and regenerate the complete manifest/archive before requesting
execution approval. Prepared data alone cannot pass the launcher's sealed-review
input-set check. Old operation approvals never authorize this new bundle.

Installation acceptance requires exact package delta/status, clean dpkg,
protected new inputs, effective needrestart policy, expected hook completion,
restored controls/automatic updates and boot/access/network continuity.
Do not replay installation after an acceptance failure; inspect its terminal
state and prepare only the necessary recovery/acceptance action.

## Source build

NTPsec 1.2.5 and GPSD 3.27.5 are pinned in the source recipe, with signed tags,
commits, publisher archives and signing fingerprints. Both archive signatures
and tags were checked, with archive/Git comparisons: all 688 NTPsec tracked
files matched; 795 GPSD tracked files matched, with seven omitted CI/ignore/AIS
sample files and release-only generated/manual/packaging material. GPSD trust
bootstrap used publisher/project HTTPS and the signed-tag identity; no
independent out-of-band maintainer certification is claimed.

The original clockmaker/pinup HOWTO is an adaptation source, not an executable
installer. Repository Python 3 helpers replace moving pulls, ignored shell
statuses, Python 2, blind OS/account/purge/reboot changes and unsupervised SysV
launching. Upstream clockmaker bytes were SHA-256
`67b52fe2bc4c94c61fdc7edd438eaf1799ff6672cfc208d85e7d79fda2e3b1d9`;
pinup bytes were
`559eb46968cd242f87fccf7bcbb4d8ad96b25545c931b174bbde1da7f6f27c5b`.
Retain attribution/provenance when changing these adaptations.

GPSD must keep timeservice=yes, magic_hat, SHM, clients, Python, ncurses,
manuals, shared libraries and control_socket. Explicit default/tested protocol
options prevent this release's time-service preset from stripping decoders.
Even passing timeservice=no enters its raw nonempty argument guard. SiRF,
Zodiac/EARTHMATE and EverMore support unchanged tests; the daemon suite also
uses other protocols. Their presence does not identify the receiver.

The reported Uputronics receiver is u-blox M8. This release includes the UBX
driver directly; ublox, mtk3301, nmea0183, fixed_port_speed and fixed_stop_bits
are not declared build options. Acceptance requires a u-blox driver listing.
GPSD's runtime `-s 115200` and checked UART initialization enforce the approved
baud rate. Receiver suffix/firmware, active wire protocol and device paths
remain target evidence. control_socket support is needed by gpsfake; it does
not select or activate a production socket.

NTPsec uses SHM refclock, NTS, seccomp, native Python extension, manual pages
and mDNS registration; HTML docs remain disabled. Remove the mDNS-disable
option and require `HAVE_DNS_SD_H` in generated `build/config.h`: waf's
header/library detection is optional and can otherwise omit support silently.
The pinned manifest includes the Avahi compatibility library and development
dependency closure. Resolve them against a fresh snapshot before installation.
Bind observed target Python module/shebang paths.
Prefix is `/usr/local`, with two jobs for both native build systems. Do not
replace selected source descriptions with APT application dependency lists.

Keep `--refclock=shm`. GPSD reads the receiver's serial data and PPS, exporting
each through SHM; NTPsec consumes those segments. `nmea` and `pps` enable direct
device drivers in ntpd and are not required to receive PPS through GPSD.
Verify the observed segment assignments before rendering host `ntp.conf`.

Offline source preparation invocation shape:

```bash
python3 -I -B ntpsec/scripts/prepare-source-build.py \
    --foundation "$foundation_spec" --foundation-sha256 "$foundation_sha" \
    --python-evidence "$python_evidence" --python-evidence-sha256 "$python_sha" \
    --sources "$verified_source_cache" --known-hosts "$pinned_known_hosts" \
    --operation-id "$new_operation_id" --output "$new_preparation"
```

The preparer verifies hashes, prerequisites/options, safe archive roots/links,
target profile and worker inputs. The operation ID renders an exclusive workspace;
hostname/kernel and SSH endpoint/key are rendered from the supplied evidence.
Reject malformed identities and ambiguous template bindings. Build execution
also checks the accepted foundation boot ID. Publisher archives do not contain a Git PAX
commit comment; authentication comes from the reviewed signature/tag/blob
chain. Only contained links to archive regular files are accepted.

Seal the complete private execution bundle with its specification, every input,
strict launcher, host key, offline tests and review. Approve its exact digest,
target, effect, acceptance and failure path before submission. Prepared data
and old approvals do not authorize contact; edits require a new hash/approval.

Native commands are GPSD SCons build/check/install and NTPsec waf
configure/build/check/install, all unprivileged with an owned DESTDIR. Preserve
full logs and failures, reject existing output paths and stop only owned child
process groups on interruption. Do not skip tests or regenerate expectations.

Waf binary tests replace inherited PYTHONPATH. clockmaker validates and exposes
the staged gps package in the owned build/main/tests/pylib path; preparation
checks the pinned layout. Standalone acceptance also sets staged PYTHONPATH
and LD_LIBRARY_PATH. Isolated imports must resolve inside the candidate.
This prevents live Python installation from being used to satisfy build tests.

Acceptance verifies the full file/link manifest, binaries/clients/manuals/modules,
ABI/imports/linkage, required GPSD/NTPsec generated features, u-blox support and
unchanged inventory/boot/access state. Only static `/usr/local` output is
accepted; etc/var configuration, escaping links and unsafe modes are rejected.
The accepted release manifest binds helper/source/dependency versions, options,
kernel, build log and every staged hash/mode. Acceptance is not live deployment.

## Live installation and rollback

First inspect all intended destinations/collisions under a separately approved
read-only scope. Source-built files may exist even when dpkg has no application
record. Capture destination types, hashes, links, ownership and modes.
For updates, also compare the previously accepted installed release and include
obsolete destinations that need removal.

Use `run-foundation-preflight.py seal-destinations` to prepare an offline bundle
from private copies of the accepted release, build specification and acceptance
receipt, each with an explicit SHA-256, the pinned known_hosts and a unique
operation ID/output directory. The checked-in helper must match the accepted
release; the build inventory must match the repository's accepted package records.
This first-install scope covers only manifest destinations and their protected
ancestors, OS/boot/Python identity, package inventory/audit and safe service/process
observations. It runs no installed application code. Bound each file hash to
64 MiB and each of two comparison passes to 512 MiB within one capture; reject
unsafe parents, special files or continuity drift. No existing files are replaced.

The [current inspection review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-destinations-20261012-v1/review.md)
was approved and executed once on j2-svntp1. Terminal readback passed full
validation: all 159 destinations are absent, with zero collisions, 27 ancestor
records and no active ntpd/GPSD processes. Exact 686-package inventory, boot,
Python and service/process continuity passed. Verified root-owned staging
cleanup completed; the accepted inspection and canonical pre-state remain private.
The native installation consumed this pre-state and passed acceptance. Activation
requires a separate reviewed bundle; the consumed inspection must not be replayed.

For future inspection bundles, use exclusive root-owned 0700 staging with
0600 hash-verified inputs. Submit once with the same
launcher/bundle/hash using `execute --mode collect`, conditionally read the same
terminal record with `--mode readback`, and clean only the verified stage with
`--mode cleanup` after retaining that readback. Readback saves `inspection.json`,
canonical `installation-state.json` and a bound acceptance receipt. Held states,
missing receipts, busy locks, changed inputs or unexpected stage entries prohibit
recollection and require separately reviewed recovery. Historical execution
records and both accepted source workspaces remain preserved. A collision or
active daemon observation is input to installation review, not replacement or
service-change authorization. HISTORY records the exact bundle hash and expiry.

The [native first-install review](/home/aaron/code/.local-evidence/homelab-ntp/current/source-install-20261012-v1/review.md)
was approved and executed once for j2-svntp1. Installation, terminal readback
and payload cleanup passed; all 159 native entries are accepted. Preparation used
only the accepted release/build evidence and destination inspection; no target
contact occurred during preparation. Executed journals, receipts and privileged
code remain retained; only the verified temporary payload was removed. For
future nodes, use `run-source-install.py seal` with private input files,
explicit `--input-hashes`, pinned known_hosts and a unique operation ID/output.
The archive binds the current source recipe, pinned assets, transport, root
helpers, tests, release, build receipt/specification and accepted inspection
receipt/specification/pre-state. Future nodes require their own accepted inputs.
Offline fixtures simulate target ownership independently of the workstation or
CI account; source ownership rejection remains an acceptance boundary.

The wrapper walks the accepted target staging tree with no-follow directory
descriptors, verifies bounded bytes/links and copies them into protected root
staging before calling the accepted native clockmaker installer. Revalidate
absent destinations, protected ancestors, exact packages, boot, Python and
service/process state. Install manifest modes with root:root ownership; retain
existing directories and create missing parents as root:root 0755 with recorded
identities. The root-owned journal keeps baseline metadata and native backups;
this first-install transaction has no prior files to back up. It accepts only
complete installed hashes/links/ownership/modes and target continuity, with
terminal readback revalidation. The result is `copied_not_activated`.

Submit once using `execute --mode collect`, then conditional `readback` with the
same bundle/hash. A held installation may use conditional `rollback` only when
all current destinations are absent or proved accepted installed artifacts,
parent identities match, created-directory contents contain no unrelated data,
and the baseline/target state is intact. Restore absent files and remove only
proved new empty directories. Missing records or ambiguous/interrupted state
require separate recovery review; never replay installation or recovery.
After retained terminal readback and completed installation or verified recovery,
`cleanup` removes only the verified temporary payload. Executed privileged code,
journals, backups and receipts remain private on target and controller. Runtime
linkage/cache discovery, configuration and activation are later reviewed gates.

Invocation shapes for the underlying helper use separately reviewed inputs:

```bash
python3 -I -B ntpsec/scripts/clockmaker.py inspect \
    --input "$release" --sha256 "$release_sha"
sudo -n python3 -I -B ntpsec/scripts/clockmaker.py install \
    --input "$release" --sha256 "$release_sha" \
    --state "$pre_state" --state-sha256 "$state_sha" --journal "$new_root_journal"
sudo -n python3 -I -B ntpsec/scripts/clockmaker.py rollback \
    --input "$installation_receipt" --sha256 "$receipt_sha"
```

An update adds --previous and --previous-sha256 to both inspect and install.
The installer rejects conflicting package applications/running ntpd or gpsd;
it does not stop them. Approve the actual pair cutover separately/in the exact
bundle. Verify all staged bytes before writes, back up replacements/removals,
recheck captured pre-state, atomically install, and record verified post-state.
Do not build as root or copy ntp.conf as part of application installation.

`copied_not_activated` is a file-installation result. Library-cache management,
Python/PATH discovery, runtime users/groups, service/config installation and
activation are explicit reviewed actions; clockmaker does not run ldconfig,
pip or systemd changes. Do not assume `/usr/local` is already discoverable.

Rollback requires the exact root-owned receipt, unchanged post-state and verified
backups with both daemons stopped. It restores prior files/links/metadata and
removes candidate-only files without activating services. Interrupted installs
or rollback need inspection and a new recovery definition, never resubmission.
Retain a tested rollback artifact, not merely an old source revision that must
be rebuilt against changed dependencies.

## Configuration and combined service

Accepted v2 observations: no matching UART/PPS/RTC device nodes or sysfs entries;
boot command line requests a serial console, while GPS UART/PPS/RTC overlays
are absent. Local ntp/ntpd/gpsd accounts and groups are absent. Ethernet uses a
NetworkManager profile at capture time; fixed dual-stack networking subsequently
passed acceptance on October 13. Avahi
and systemd-timesyncd are active, while application time-service units are absent.
Disable the conflicting time writer only in the reviewed NTPsec cutover.

Both installed Python package roots match the isolated root search path's
`/usr/local/lib/python3.13/dist-packages`; this does not prove runtime-user imports
or access. `/usr/local/lib` is already in loader configuration, but installed
libgps libraries are absent from the cache. Review cache refresh and bounded
runtime-user/library validation separately; do not add an unnecessary loader
path or Python bridge. Resolve hardware wiring/boot includes, daemon account and
device access, listener/upstream/restriction choices and service recovery before
rendering a deployable host configuration. Phase 3's fixed networking and hardware
bring-up precede service activation.

The [v2 runtime discovery review](/home/aaron/code/.local-evidence/homelab-ntp/current/runtime-discovery-20261012-v2/review.md)
was executed once and accepted for j2-svntp1. Capture, terminal readback and
observation-stage cleanup completed with status 0. All 159 installed entries,
parent identities and target continuity passed. Prior native journals, source
workspaces and executed evidence remain preserved. No configuration or activation
was performed. For future nodes, prepare their own discovery offline and obtain
separate execution approval.
The checked-in controller binds the accepted native installation archive,
readback/acceptance and successful payload cleanup, current recipes, pinned
assets, templates and snapshots of the three governing documents. Exact receipt
and bundle hashes are required; a historical node's receipt is not a fresh-node
baseline. Preserve the accepted installation stage and both source workspaces.

```bash
python3 -I -B ntpsec/scripts/run-runtime-discovery.py seal \
    --installation-dir "$accepted_installation_directory" \
    --installation-sha256 "$accepted_installation_bundle_sha256" \
    --operation-id "$unique_operation_id" --output "$new_private_output"
```

One root-owned 0700 observation stage holds only sealed 0600 inputs. The capture
verifies installed files/links twice, protected parent identities and exact
package/boot/Python/service continuity. It reads bounded boot/time/loader files,
approved drop-ins, UART/PPS/RTC metadata and sysfs names/paths/drivers; local
account/group identifiers omit password fields. Fixed read-only queries gather
addresses/routes, NetworkManager profile identifiers/device state and service
properties. `ldconfig -p` observes cache contents; `readelf -d` inspects native
ELF dependencies. It imports no installed application/Python extension and opens
no serial/PPS/RTC device. It does not query Wi-Fi secrets or `/etc/shadow`.
The recorded isolated root Python search/scheme paths and effective PATH are
that capture context; runtime account/operator environments still need review.

Use the reviewed bundle/hash with `run-runtime-discovery.py execute --mode collect`,
then conditional `readback` and `cleanup`. Each mode registers once before SSH;
full streams/statuses remain private. Readback checks the terminal/report/spec
hashes, complete installed coverage and scope before writing `runtime.json` and
its acceptance receipt. Recovery is readback only; a lost terminal requires a
separately reviewed state inspection. Cleanup validates the retained terminal
hash and every expected staging entry before removing this observation stage.
Unknown entries hold cleanup; prior installation journals/evidence remain intact.

Review accepted `runtime.json` before rendering the configuration profile with
the existing `clockmaker configure` workflow below. Missing devices/accounts,
unresolved boot includes and provider/listener/access choices remain explicit
inputs requiring resolution. Static metadata does not prove dynamic linkage,
Python imports, GNSS firmware/fix, PPS health or physical wiring. Configuration
readiness remains false until these requirements and the reviewed host choices
are satisfied. Runtime execution tests, library-cache changes, account/device
setup, fixed dual-stack networking, file deployment and activation require later
explicit approval, backups and acceptance under Phase 3.

The supplemental `host-inputs-20261012-v1` review used the same guarded
read-only collector and accepted native receipt. It adds all registered Ethernet
profiles' connection/Ethernet/IPv4/IPv6 properties by UUID, with unchanged
registry/properties required across capture. Wi-Fi, 802.1X and VPN settings,
secrets and raw NetworkManager profile files are excluded. It also records
nobody/nogroup, serial-getty/Bluetooth enablement state and the installed
disable-bt, pps-gpio and i2c-rtc overlay bytes/hashes. Overlay availability is
not proof of board wiring. Prior v2 evidence remains preserved.

The [supplemental review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-inputs-20261012-v1/review.md)
was approved and executed once; capture, terminal readback/acceptance and scoped
cleanup all returned worker/transport status 0. Approved bundle SHA-256:
`2420d0276107b8a10c12da8ffefd3b245611fc0aa8383de5b36fca086f13603a`.
Accepted runtime report SHA-256:
`954736cd1068a48c4178001042dda8efc18f4b41bc1f5b9bac524003fc03279a`.
Removed only its root observation stage. Raw evidence and prior native
installation journals/source workspaces remain private and preserved.

The one Ethernet profile is bound to eth0 with autoconnect enabled; both address
families use automatic configuration, no explicit addresses/gateway/DNS, and
automatic DNS is currently permitted. Its observed properties are the baseline
for guarded networking preparation. nobody/nogroup and dialout exist; ntp,
ntpd and gpsd accounts/groups remain absent. All three overlay files are
present, including rv3028 and PPS gpiopin metadata. No UART/PPS/RTC device was
observed. hciuart is absent; queried serial-getty units are disabled/inactive.
Avahi and bootstrap timesyncd remain enabled/running. All 159 native entries
and 686 package records retained accepted continuity. Configuration readiness
and activation authorization remain false.

Fixed networking has passed acceptance with timed recovery and new-address
checks. Prepare subsequent mutations in this order: hardware boot edits with
confirmed PPS GPIO/RTC, byte-exact backups and console/reboot recovery; then
runtime accounts, loader checks and staged application configuration. Bootstrap
timesyncd remains active until the separately approved clock-discipline cutover.
Do not create a gpsd account by assumption: pinned GPSD 3.27.5 SConscript
defaults to nobody/dialout; confirm the accepted build's privilege settings and
device access before selecting identities. Retain accepted native file modes;
root launch or diagnostic access does not establish unprivileged client access.
The foreground GPSD template now includes `-n` to poll without a client, as
specified by the pinned GPSD manual, together with `-N` and 115200 baud.
NTP account choice, UART path, SHM ownership, leapfile, provider/listener scope
and runtime imports require reviewed inputs and acceptance before activation.

Do not create a deployable ntp.conf or select UART/PPS/RTC overlays without
observed target inputs. The approved Uputronics revision on the rebuilt node
is reported as 5.9 (2020). The operator-supplied Uputronics GPS/RTC datasheet,
document revision 2.2 (December 2020), specifies PPS on BCM GPIO18 (header pin
12), an RV-3028-C7 RTC at I2C address 0x52, and serial operation at 115200 baud
(pages 1, 2, 4 and 5). GPIO18 is not physical pin 18. Prepare explicit
`dtoverlay=pps-gpio,gpiopin=18` and `dtoverlay=i2c-rtc,rv3028` candidates only
after checking the target's installed overlays and boot configuration. The
datasheet's revision identifies the document, not the physical board revision.
Primary-node HAT/power details still need their own observations. Verify actual
device aliases, permissions, PPS edge, RTC behavior, firmware/fix and stack/fan
compatibility before accepting bring-up. The datasheet notes that after a cold
start, the time pulse can take up to 12.5 minutes while time parameters,
including leap seconds, become known; positional lock alone is not PPS readiness.

Treat the datasheet's Raspbian commands as historical examples. Do not infer
the UART alias from `/dev/ttyS0`, copy `/boot/config.txt` paths, change hwclock
udev rules, remove packages, scan I2C or open the receiver from this document.
Those actions require a target-specific reviewed stage. The supplemental
read-only bundle remains unchanged and has now been executed and accepted;
the datasheet authorizes no additional execution.

### Hardware boot and runtime prerequisite transactions

The checked-in [hardware recipe](../configs/host-hardware-recipe.json) and
[runtime recipe](../configs/host-runtime-recipe.json) define separate stages.
[run-host-configuration.py](../scripts/run-host-configuration.py) seals them
without target contact; [host-configuration-stage.py](../scripts/host-configuration-stage.py)
uses the existing protected file guards and networking checks. Bind an accepted
network archive, its durable dual-endpoint acceptance and successful cleanup,
current recipes, pinned asset/source/package manifests, native release and all
three governing document hashes. Each stage uses a unique operation ID and an
exclusive root-owned 0700 directory with 0600 inputs, before-state and receipts.
Preserve prior executed archives, root journals and private evidence.

Prepared reviews for j2-svntp1:

- [Hardware/boot review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-20261013-v1/review.md):
  two guarded boot-file edits, one console-ready controlled reboot, dual-stack
  management and UART/PPS/RTC metadata acceptance, conditional readback, file
  restoration, one recovery reboot when needed and transient cleanup.
- [Account/runtime prerequisite review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-runtime-20261013-v1/review.md):
  conditional on that exact hardware specification's accepted post-reboot state;
  dedicated NTP account, cache refresh, isolated native/Python checks and a
  private rendered service candidate, with guarded recovery and cleanup.

Each private directory's `sealing.json` records its exact archive SHA-256.
Preparation is not execution approval. Do not replay consumed operation modes.

```bash
python3 -I -B ntpsec/scripts/run-host-configuration.py seal \
    --kind hardware --network-dir "$accepted_network_directory" \
    --network-sha256 "$accepted_network_bundle_sha256" \
    --operation-id "$unique_hardware_operation_id" --output "$new_hardware_output"
python3 -I -B ntpsec/scripts/run-host-configuration.py seal \
    --kind runtime --network-dir "$accepted_network_directory" \
    --network-sha256 "$accepted_network_bundle_sha256" \
    --hardware-dir "$sealed_hardware_directory" \
    --hardware-sha256 "$sealed_hardware_bundle_sha256" \
    --operation-id "$unique_runtime_operation_id" --output "$new_runtime_output"
```

Hardware preparation preserves unrelated boot settings and the storage/root
command line. The candidate adds `enable_uart=1`, `dtparam=i2c_arm=on`,
`dtoverlay=disable-bt`, `dtoverlay=pps-gpio,gpiopin=18` and
`dtoverlay=i2c-rtc,rv3028` under `[all]`. Remove only the observed
`console=serial0,115200`; retain the local display console. Existing hardware
directives/includes and unexpected serial-getty/hciuart states hold preparation
or execution for review. No service enablement change is included.

After separately approved `execute --mode start`, use `--mode reboot
--console-ready` only when console/media recovery is available. There is no
automatic recovery timer across reboot. `--mode verify` requires a new boot ID,
matching kernel, packages, native files and protected configuration, retained
network profile/DNS/routes/HTTPS egress, and pinned SSH over both fixed addresses.
Record the observed PL011 `serial0` target and driver, character-node permissions,
BCM18/rising PPS device-tree mapping and RV3028 node at I2C 0x52. Do not infer
numbered UART/PPS/RTC names. Enabling overlays includes normal kernel driver
probing and RTC boot-time use. No user-space device probe or RTC-setting command
is included; GNSS fix, physical pulse health,
RTC time/accuracy, PoE/thermal behavior and NTP client responses remain later
acceptance gates. This stage accepts boot/network persistence and device metadata.

On failure, conditional `--mode readback` preserves terminal state. `--mode
recover` restores both boot files only if each matches its before-state or
sealed candidate with unchanged ownership/mode. Before reboot, no recovery
reboot is needed. After reboot, `--mode recovery-reboot --console-ready` and
`--mode verify-recovery` restore and verify the original boot configuration and
retained management access. Lost endpoints/boot failure require console/media
recovery using the retained before-state and original card. Unrelated drift
holds recovery. Preserve the primary and its shared antenna-power path.

If SSH is unavailable but the target boots, log in as `ama` on its console and
invoke the preserved worker through `sudo /usr/bin/python3 -I -B
/var/lib/ntp-host-OPERATION/host-configuration-stage.py --root
/var/lib/ntp-host-OPERATION --mode readback`, substituting the reviewed operation
ID. The same entry supports `recover`, `recovery-reboot --console-ready`,
`verify-recovery` and `cleanup`; it cannot apply a new stage. Its protected file,
identity and drift guards still apply. Do not repeat a reboot submission after
an uncertain reply. If the OS will not boot, use console/media recovery and the
preserved original card; do not touch the primary's power or splitter mapping.

The retained hardware v4 candidate passed the separate hardware acceptance
continuation on October 13. Both management endpoints and all required
network/native/device-metadata checks passed; evidence-only cleanup closed
the continuation. No boot edits, reboot, service actions or device opens
occurred. The separate receipt is authoritative for the next runtime gate;
original v4 state remains unchanged. Preserve the executed
[acceptance-only review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-hardware-acceptance-20261013-v1/review.md)
and its `sealing.json` hash. This is a new schema-3 hardware stage, prepared
with `run-host-configuration.py seal-acceptance --hardware-dir SOURCE_DIR
--hardware-sha256 SOURCE_HASH --timing-dir INSPECTION_DIR --timing-sha256
INSPECTION_HASH --operation-id UNIQUE_ID --output NEW_PRIVATE_DIRECTORY`.
The source is immutable hardware v4; the timing inspection must be accepted
and cleaned. Preparation verifies both archive manifests, diagnostic receipt,
terminal hash, candidate boot, source specification and boot-file hashes.
Current helpers, tests, recipes, pinned manifests and governing documents
are bound in the new archive.

Its execution permits only `start`, `verify`, conditional `readback` and
`cleanup`. Start creates protected evidence only. Verification holds the
original stage lock shared/read-only, rejects original-state or candidate
drift, and obtains matching proofs through both pinned management endpoints
before writing a separate hardware receipt. PPS validation correlates the
virtual class name and device number with the bound platform's BCM18/rising
mapping. No devices are opened. The new stage does not edit boot files,
reboot, restore files, change services or rewrite v4's acceptance state.
Cleanup marks only the new evidence stage closed, including after a hold;
all original and continuation artifacts remain preserved. Readback remains
available if candidate/source drift prevents further validation. Do not
replay a consumed mode after uncertain output.

The original v4 controller is preserved and verified offline at
`host-hardware-20261013-v4/recovery-controller/ntpsec/scripts/run-host-configuration.py`
under the private evidence directory. Use that byte-exact controller with
v4's original archive/hash for its remaining approved recovery modes;
the current controller intentionally rejects older launcher bytes. The
original console worker also remains available. Preparation did not invoke
recovery or contact the target. Account/runtime v2 is now accepted against the
hardware continuation specification and receipt; operation cleanup completed.
Do not execute the older account/runtime bundle bound to hardware v1.

The executed [account/runtime v2 review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-runtime-20261013-v2/review.md)
and its `sealing.json` bind the accepted hardware continuation, baseline v3,
accepted networking and current repository inputs. The archive includes
the complete hardware acceptance receipt and evidence-closure record;
offline verification rechecks their hashes, boot identity and endpoint proofs;
live preflight must still prove the exact accepted hardware stage and current
boot before creating the account or refreshing the loader cache. The approved start and
dual-stack acceptance completed once, followed by operation cleanup. Native
versions, libgps cache resolution, isolated root/GPS/NTP and NTP-user Python
imports, UART group access and the private service candidate passed validation.
The dedicated NTP identity and refreshed cache remain in place. No service
installation/activation, reboot or device I/O occurred. Readback and recovery
were unnecessary. Preserve backups, candidates and every prior executed record.
Next prepare final NTP configuration and the GPSD/NTPsec service cutover with
acceptance/recovery for separate execution approval.

Historical baseline/hardware archives are validated as executed provenance:
exact archive and member hashes, closed membership, accepted terminal records
and target bindings. Their older launchers need not equal current repository
code. Execution still requires the exact current sealed launcher and
transport. The runtime start window ends no later than the accepted hardware
receipt's 24-hour gate; any live state drift holds before mutation.

The runtime stage requires the exact hardware root specification, accepted
checks and current accepted boot ID. Create only a dedicated `ntp:ntp` system
identity, with `/nonexistent` home, no home creation and nologin shell. Retain
GPSD's pinned-build `nobody`/`dialout` identities. Capture sanitized local
identity fields; do not capture password/shadow data. Names already present
require a fresh review. Back up `/etc/ld.so.cache` and run `ldconfig -X`, leaving
library symlinks and loader configuration unchanged. Preserve all accepted
native modes, including root-only GPSD/client files.

Validate the libgps cache entry, root native versions, isolated root GPS/NTP
imports and isolated NTP Python imports under `ntp`. Check observed UART group
access against `dialout`. Render the service JSON using the accepted `serial0`
alias, 115200 baud, foreground GPSD with nowait and foreground ntpd with `-m`
and `ntp:ntp`. Validate it and the existing service template on the target. Keep
both candidates inside the private stage; install no global service/config file
and activate no daemon. Bootstrap timesyncd remains active. Final `ntp.conf`,
SHM ownership/units, upstreams, restrictions, drift/leap paths, Avahi scope,
service installation and clock cutover need their own reviewed stage.

Runtime recovery restores the recorded cache only while it still matches its
original or recorded refreshed bytes. Remove only the recorded newly created,
unchanged, idle NTP identity/group. Unrecorded partial account/cache mutation or
unrelated drift holds for inspection; do not delete an inferred identity. No
home or data directory was created and no recursive deletion is used. Accepted
stages require a new review for reversal. Terminal cleanup stops/resets only
operation reboot timers/services, retaining before-state, candidates and all receipts.

### Fixed dual-stack networking transaction

Use [host-network-recipe.json](../configs/host-network-recipe.json) with
[run-host-network.py](../scripts/run-host-network.py) and
[host-network-stage.py](../scripts/host-network-stage.py). Preparation consumes
a fresh accepted host-input report, its immutable archive, terminal acceptance
and cleanup receipts. It binds the original Ethernet UUID, MAC, DHCP endpoint,
boot/kernel, package/native/service state, pinned SSH key and all three governing
documents. No historical package counts or network profiles are hard-coded.

```bash
python3 -I -B ntpsec/scripts/run-host-network.py seal \
    --snapshot-dir "$accepted_host_input_directory" \
    --snapshot-sha256 "$accepted_host_input_bundle_sha256" \
    --operation-id "$unique_operation_id" --output "$new_private_output"
```

`host-network-20261013-v1` was executed and accepted on October 13, 2026, with transient-unit cleanup complete. Its immutable scope is recorded in the
[private review](/home/aaron/code/.local-evidence/homelab-ntp/current/host-network-20261013-v1/review.md).
The accepted host uses `10.1.0.51/22` and `fd36:5aa8:6971:1::51/64`, with IPv6 RA retained. Both fixed addresses passed pinned-key SSH checks; all ten acceptance checks passed, including DNS VIPs, routes and HTTPS egress in both families. Durable acceptance preceded recovery-timer cancellation. The original DHCP profile, root journal and private execution evidence remain available. Reboot persistence and NTP client acceptance remain pending. Do not replay the consumed operation; prepare hardware/boot and account/loader/runtime stages for separate approval.

Its scope is one background apply job, endpoint acceptance, conditional
readback/recovery and transient-unit cleanup on j2-svntp1. Before mutation,
require original profile/registry/active-interface continuity, the recorded
bootstrap address, protected executable locations and a negative IPv4 ARP
duplicate probe. A negative probe does not establish administrative ownership;
the governing plan allocates the addresses. Validate IPv6 DAD after activation.

Clone the original profile under the unique operation name and record its
allocated UUID. Configure manual IPv4, fixed ULA alongside automatic IPv6/RA,
the two DNS VIPs, automatic-DNS rejection in both families, required IPv4/IPv6
and candidate autoconnect priority 100. Preserve other observed settings.
Disable original autoconnect and activate the candidate. Retain the original
profile and exact observed properties as the recovery baseline; rollback restores
settings rather than promising byte-identical NetworkManager keyfile formatting.
Only connection.timestamp is volatile in profile comparisons.

The isolated root apply service has a 180-second runtime bound. Before creating
any profile, arm an independent root systemd timer that invokes recovery after
300 seconds even if SSH is lost. Require exact candidate/retained-original
properties, fixed addresses without DAD failure, a public IPv6 address and RA
default route, correct IPv4 gateway, source-bound DNS routes, exact effective
DNS VIPs and ICMP reachability to both VIPs. Source-bound HEAD HTTPS requests to
`https://deb.debian.org/debian/` over both families prove DNS/TLS/egress without
downloading payloads; disable curl configuration and proxies.
Read protected resolver configuration and require the direct two-VIP nameserver
view before and after activation. A local resolver stub or other upstream DNS
holds preflight for separate review rather than assuming its forwarding policy.

Use the approved bundle/hash with `execute --mode start` once. Then use
`execute --mode verify`: bounded read-only polling waits for applied state;
pinned-host-key SSH must succeed at both new fixed addresses before one
conditional acceptance. Require all labelled checks to be true and at least
45 seconds to remain. Persist acceptance before cancelling the timer, so a lost
cancellation response cannot leave an uncommitted change without recovery.
Conditional `--mode readback` can recover a durable acceptance receipt after
transport loss. Never resubmit a lost start, acceptance or recovery action.

Readback may locate the operation at new IPv4, new ULA or the old DHCP endpoint
using the same pinned key. Conditional recovery first locates the stage with
read-only calls, then submits one action. Restore original autoconnect, activate
the original profile and remove only the proved operation candidate. Unexpected
original/candidate drift holds recovery for review. DHCP restoration cannot
guarantee the previous lease/address; console access is required if endpoints,
the timer or recovery are unavailable. No reboot is authorised by this stage.

After accepted/recovered state, `--mode cleanup` stops/resets only operation
transient units. Keep the protected root stage, before-state, bounded command
streams/status journal and receipts for recovery/audit. All controller streams
and registered submissions remain private. Preserve prior executed evidence,
native installation journals and source workspaces. Target NetworkManager and
systemd execution remain untested during offline preparation; required queries,
timer arming and state comparisons hold on errors. Reboot persistence belongs
to the later hardware/reboot acceptance gate.

clockmaker configure takes a hash-bound profile with schema/hostname,
ntp_config and unit path/hash objects, plus explicit timeservice gpsd/ntpd
argument arrays and uart_device. It stages configuration only:

```bash
python3 -I -B ntpsec/scripts/clockmaker.py configure \
    --input "$configuration_profile" --sha256 "$configuration_sha" \
    --output "$configuration_candidate"
```

GPSD requires foreground -N and exactly one -s 115200 matching the observed
UART. ntpd requires foreground -n, -m, -c /etc/ntp.conf and a reviewed -u account.
Use timeservice.json.example only as a schema example; unresolved @...@ values
must be rendered/reviewed, not installed. Select GPSD listener/socket scope,
export and privilege/device access explicitly. Validate NTP restrictions,
upstreams/NTS, drift/leap paths and SHM GPS/PPS configuration against the pinned
build's manuals and actual device/service evidence.

In NTPsec 1.2.5, mDNS is enabled by ntpd's `-m`/`--mdns` startup option,
not by an `ntp.conf` enable directive. The optional `mdnstries 5` entry in
`ntp.conf` sets registration retries and is already the default. Once ntpd
synchronizes, verify its registration journal and browse `_ntp._udp` from
another client on the intended network; verify the advertised host/port and
IPv4/IPv6 reachability. Registration alone does not establish time-service
acceptance. Inspect Avahi service state, interface policy and UDP 5353
multicast permissions; do not enable reflection implicitly. Retain NTP
restrictions and the governed unicast DNS/SRV records.

The proposed timeservice.service runs `/usr/local/libexec/timeservice.py` with
root-protected `/etc/ntpsec-timeservice.json`. The supervisor checks stty
initialization, launches both foreground daemons, stops both if either exits
and returns failure. Systemd restarts the pair with the template's bounded
retry policy; an operator stop succeeds and does not trigger automatic restart.
KillMode covers the whole cgroup. Launch order does not prove GPS/PPS readiness.

Deploy configuration files/units with explicit root ownership/modes and
backups, validate rendered units and NTP syntax, and approve activation/cutover.
Disable competing package services/sockets and other time providers only in
that reviewed operation. Require individual process identities/cgroups,
GPS/PPS convergence, IPv4/IPv6 UDP 123 clients, upstream/NTS behavior, offsets,
jitter, reach, leap state, metrics and journals after restart/reboot.

pinup queries or edits only reviewed `/boot/firmware/config.txt`, with approved
hostname, exact input hash and confirmed BCM GPIO. It preserves comments and
other overlays, rejects conditional/duplicate/include ambiguity, backs up bytes
and atomically writes; unchanged settings are a no-op. It does not reboot or
prove effective overlays/PPS pulses. Reboot and device acceptance are separate.

## Needrestart and notification

The installed policy template retains list-only reporting, kernel checking,
Pi 4/v8 filtering and no built-in notification; ucodehints=0 disables the
processor microcode check requested for this platform. Kernel report status 1
was the accepted report's current-kernel result, not completion of mail/cron.
Do not apply a Pi 5/-2712 filter or disable kernel checking as a side effect.

needrestart.sh is now a byte-exact repo asset vendored from the shared server
configuration project, with provenance in asset-provenance.json. Its cron
example uses flock and the shared daily reporting model; render both recipient
variables and review schedule/timezone before installation. Install the script
at `/usr/local/sbin/needrestart.sh` and rendered cron at
`/etc/cron.d/needrestart_check` with explicit root ownership/modes. These files
have not been deployed on the rebuilt node.

Install the separately reviewed mail group and configure sendmail-compatible
msmtp-mta. msmtprc.example follows the existing LAN Mailrise model with
reviewed host/port/domain; its unauthenticated non-TLS mode requires a trusted,
restricted LAN path. Credentials, if needed for another provider, remain in
protected secret files and are never committed. Protect `/etc/msmtprc` as
root:root 0600 and verify the selected sendmail account/path.

Syntax/pretend-mode checks do not prove delivery. Sending a synthetic or real
notification requires approval for the exact destination/content. Accept the
script, cron failure path and actual Mailrise delivery without unattended
restarts of the combined time service. No notification test was sent during
repository consolidation. Final user-managed passwordless sudo removal is a
separate end-of-project action, not an installer side effect.

## Optimization evaluation and measurement

[Phase 3A and the proposal register](ntp-architecture-deployment-plan-v1.0.md#phase-3a-evaluate-and-accept-measured-optimizations)
own optimization decisions. Add each future proposal there with a stable ID,
evidence, disposition and owning phase. Keep operational outcomes in HISTORY;
do not create a separate tuning runbook for each experiment.

OPT-001 does not change the current package/build recipe. pps-tools, source-built
GPSD/NTPsec, static network settings, verified UART/PPS overlays and exclusion
of competing time daemons are baseline work in their existing phases. CPU
isolation, performance-governor policy, arm_freq and GPU allocation remain
unadopted candidates until measured on an accepted node. Do not paste the
proposal's APT command or boot/config.txt block onto a target.

For an experiment, prepare a fresh scoped collection and a hash-bound bundle
with exact settings, comparison metrics/window, baseline backups, acceptance,
restoration and any reboot/console recovery. Verify active clocksource, kernel
options, CPU policies, task/IRQ placement and hardware mapping before choosing
controls. Keep the peer and shared antenna power available. Run one change at
a time; allow clock convergence and representative load/thermal cycles. Use
identical logging/sampling for baseline and candidate so instrumentation does
not become the apparent optimization. Preserve GPS/PPS sequence, SHM, source
and client timing evidence separately; they measure different parts of the
path. A kernel PPS pulse report alone is not end-to-end acceptance.

The accepted staged manifest already includes pinned-source ntpviz and its
manual. Plotting is optional and does not authorize deploying that candidate.
Prefer collecting bounded NTP statistics on the node and generating graphs on
the operator workstation. Review statistics paths, permissions, rotation,
retention and transfer; review compatible Python modules and pinned gnuplot
dependencies on the analysis host. Do not install distro ntpsec-ntpviz or copy
ARM binaries/extensions onto a workstation of another architecture. Plot
generation must not add an unreviewed public web service or unbounded log load.

After accepted tuning, mirror the actual persistent settings and metadata into
the maintained repo assets, update HISTORY and repeat affected service/network,
thermal/power and reboot checks. Restore ineffective or inconclusive changes;
record deferred candidates without treating them as incomplete mandatory work.

### Antenna quality, serial calibration and fallback

[OPT-002](ntp-architecture-deployment-plan-v1.0.md#opt-002-indoor-antenna-placement-and-shm-calibration)
reviews indoor/window placement and the proposed SHM/selection changes. Begin
with scoped evidence collection, not global thresholds or a copied time1.
Confirm antenna location/model/mounting, splitter/power mapping and cable
health; identify the actual receiver model/firmware, GPSD endpoint, serial/PPS
SHM assignments and current host configuration. The antenna is shared, so
approve any move or reconnection with both services' impact and restoration.

Use pinned GPSD clients through the running daemon for observation. Do not
open its UART separately or send gpsmon/UBX configuration commands during a
read-only capture. Collect signal-strength units and used/visible satellites,
geometry/fix status, time validity and receiver time accuracy where exposed.
Correlate those records with PPS sequence gaps, SHM timestamps/freshness,
ntpq source state, loopstats/peerstats/clockstats and client timing. Record load,
temperature, capture timing and placement so later comparisons are meaningful.
Protect location/raw receiver records as bounded private evidence. Review
statistics ownership, retention/rotation and compatible off-host plotting
before deploying logging; no logging or receiver access is authorized here.

For calibration, establish a repeatable bias and a reference of known quality.
Document any time1 correction in seconds using sustained measurements.
Serial calibration and PPS/antenna-cable timing corrections are separate paths.
An offset against a PPS-disciplined system can characterize serial timing but
does not independently validate that PPS source's absolute UTC accuracy.
Document correction sign/uncertainty and compare after convergence.

The governed configuration path is `/etc/ntp.conf`. mindist/maxdist are global
selection controls, not receiver sensitivity or loss-of-fix settings. Decide
the serial SHM role and precision from the accepted source-selection profile.
Define accepted GPS/PPS loss, network fallback, stale-sample rejection and
recovery behavior in the runtime acceptance bundle. Preserve truthful leap/stratum reporting and
do not force invalid GPS time to remain selected.

### Serial latency and scheduler experiments

[OPT-003](ntp-architecture-deployment-plan-v1.0.md#opt-003-serial-latency-scheduling-and-irq-affinity)
reviews setserial, FIFO priority and IRQ affinity.
No tuning or restart is selected. Capture actual UART/driver, receiver message
schedule, SHM mappings and full association status before inferring a scheduling
problem. Do not apply an 8250 recipe to PL011 or use rc.local to persist an
unverified flag.

If measurements justify a scheduling experiment, bind observed policies and
priorities for the supervisor, both daemons and relevant threads, plus CPU
placement, IRQ source/allowed/effective affinity, counters and RT limits.
Account for daemon priority changes and service-child inheritance. Do not
substitute a stock gpsd.service override for the combined lifecycle. Test one
change with explicit access/starvation recovery and exact restoration; inspect
the actual Raspberry Pi kernel and any irqbalance policy. An accepted IRQ
setting must identify the device dynamically, not preserve an example IRQ ID.

Any necessary restart belongs to the reviewed timeservice transaction with
before/after state and both daemons' acceptance. Do not restart stock GPSD or
NTPsec units, remove IPC segments or treat a restart as proof that SHM was
cleared. Prefer bounded logging over simultaneously changing serial flags,
priority, IRQ placement and calibration; retain the next-day data privately
with configuration and sampling metadata.

### GPSD HOWTO measurement and network tuning

[OPT-004](ntp-architecture-deployment-plan-v1.0.md#opt-004-gpsd-time-service-howto-tuning)
evaluates the applicable HOWTO proposals. Begin after the combined service and
hardware baseline are accepted. Verify continuous GPSD acquisition and actual
kernel PPS capture, not just the presence of pps-tools. Preserve the existing
UART/PPS ownership and SHM mapping.

For an approved ntpviz comparison:

1. Render `statistics loopstats peerstats`, the observed `statsdir`, and daily
   `filegen` settings into the candidate `/etc/ntp.conf`. Resolve writable
   ownership under the daemon account and service sandbox, rotation/retention,
   storage budget and backup/restoration before enabling capture. Add clockstats
   or receiver/temperature collection only where needed and supported.
2. Keep separate baseline and candidate directories, configuration hashes,
   exact UTC windows, source identities and load/thermal records. Capture
   convergence separately from the comparison window. Use several hours after
   a poll change and comparable daily cycles where temperature is relevant.
3. Transfer bounded logs privately and generate plots on the workstation using
   the matching NTPsec Python modules, ntpviz and reviewed gnuplot installation.
   Use the same `--datadir`, `--starttime` and `--endtime` window for
   `--local-offset`, `--local-jitter`, `--local-stability`, `--peer-offsets`
   and `--peer-jitters` views. Read actual peer identifiers from peerstats.
   Temperature/GPS plots require the documented `temps`/`gpsd` input formats;
   ordinary journal output is not a substitute.
4. Compare serial and PPS peers separately, local frequency/wander and
   independent client timing. Record gaps, loss/fallback and outliers alongside
   distributions. A plot against the disciplined system clock characterises
   that path; absolute UTC claims still require an independent reference.
5. Trial the PPS SHM association's poll interval as one change, preserving its
   unit, calibration and selection settings. Review the accepted interval
   against shorter supported intervals, then restore or retain from measured
   offset/jitter, frequency stability and client results. Persist an adopted
   value in the rendered host configuration and installation manifest.

For network-path trials, bind the observed interface/driver, switch port,
addresses/routes and actual next-hop MAC. Collect IPv4 ARP/IPv6 neighbour
state and packet-delay evidence under a reviewed capture scope. Distinguish
link-layer resolution from upstream server and PPS behavior. A lower network
poll ceiling needs a compatible minimum and the server's rate policy; avoid
changing all upstreams to keep a neighbour entry alive.

Read EEE support/negotiation and software timestamp capabilities using the
observed interface with `ethtool --show-eee` and `ethtool -T`, if available in
the approved collection. An unsupported response closes that trial; enabled
but inactive EEE is not evidence of LPI latency. For an applicable EEE trial,
save the exact advertisement/LPI settings and restoration method before
changing them. Review switch-port changes in homelab-network. Verify link
recovery, IPv4/IPv6 client timing, errors, power/temperature and persistence
after any accepted host or switch policy.

Keep governor, tick and fan-policy experiments separate. Capture supported
controls and actual behavior, use the Phase 3A comparison/recovery process,
and preserve PoE fan safety and peer/shared-antenna continuity. Optional tools,
collectors or persistent policies need checked-in inputs and verified pins
when selected; this review adds no installation dependency.

Software PTP needs a separate server/client/network design before a bundle.
Define the client accuracy goal, timestamp capability, transport/domain,
clock ownership, elections, UTC/holdover reporting and unique SHM allocations
where used. Prevent a server selecting its own redistributed clock or a PTP
servo competing with NTPsec. Do not activate the HOWTO's sample ptp4l service
or feed a new SHM association into the current server profile.

### M8 receiver configuration trials

[OPT-005](ntp-architecture-deployment-plan-v1.0.md#opt-005-uputronics-u-blox-m8-receiver-tuning)
owns receiver-tuning decisions. Prepare a separately approved transaction
after identifying the exact module, firmware, protocol and configuration.
Use GPSD 3.27.5's ubxtool through the reviewed GPSD endpoint and explicitly
selected device. In this tool, `--device` selects a device managed by GPSD;
direct serial access uses `--file` and needs exclusive ownership and the
observed 115200 baud. Any direct-access transaction must coordinate the
combined service's stop/start and client impact. Do not open the UART alongside
GPSD. `MON-VER` establishes `-P`; command support follows that version.

1. Preserve raw receiver identity and affected configuration replies privately,
   with timestamps, message hashes and target binding. Capture NAV5, supported
   GNSS/channel allocation, power mode, NMEA/output configuration, ITFM and TP5
   as applicable. Define exact restoration messages before writing. Preserve
   the primary's shared-antenna power and operate on one receiver at a time.
2. Trial one justified change in volatile state where supported. The pinned
   tool's `MODEL,2` changes the NAV5 dynamic model; `CFG-PMS,0` selects full
   power on supporting receivers. These are mutation inputs for a sealed
   bundle, not approved commands. For composite messages, preserve unrelated
   fields; in particular a partial TP5 command can supply defaults for omitted
   fields instead of retaining the receiver's current values.
3. Read back settings and prove effective behavior. An ACK or lack of errors
   does not establish that a GNSS combination was applied. Compare acquisition,
   valid time, used satellites/accuracy, PPS gaps, serial/PPS SHM, NTP frequency
   and client timing under the OPT-004 measurement procedure. Capture any
   additional fields changed by a predefined power setup.
4. Save only an accepted configuration using reviewed masks and observed
   storage support. Define any required cold start and outage window from the
   actual change and manufacturer guidance. Verify reacquisition, valid UTC,
   PPS/SHM freshness, source selection and service/client recovery; then verify
   persistence across the approved restart/power cycle. Restore receiver and
   host settings if acceptance fails; an SD-card swap alone is insufficient.
5. Check in adopted desired settings, firmware/protocol constraints, complete
   command/message inputs, hashes, acceptance and restoration in the maintained
   installer assets. Keep receiver identifiers, location and raw captures
   private. Include the branch-specific RF-delay calculation and uncertainty
   for any TP5 correction. Until adoption, no new receiver profile is installed.

### System and Ethernet moderation trials

[OPT-006](ntp-architecture-deployment-plan-v1.0.md#opt-006-applicable-system-tuning)
reviews the applicable system proposals. Reuse OPT-001/OPT-003/OPT-004 for
previously reviewed hardware, scheduling and thermal/network controls.

For an approved coalescing trial, capture the observed interface/driver and
kernel, full `ethtool --show-coalesce` output, supported controls, adaptive
state, link settings and packet/error counters. Save the exact baseline and
restoration command before changing one supported setting. Choose the effective
RX delay from this driver's readback and granularity; account for frame
thresholds and adaptive RX behavior. Compare independent client timing,
IRQ/CPU load, PPS/SHM continuity, loss and temperature under matched idle and
busy-link windows using OPT-004 statistics. Keep EEE and CPU/IRQ placement
unchanged for this comparison. Restore if the lower moderation provides no
repeatable improvement or harms time-service health.

An adopted policy must use the observed interface and tool path, supported
parameters and verified restoration values in a maintained installation asset.
Use the supported network-manager mechanism or a reviewed unit with explicit
device readiness and failure reporting. Verify reapplication after reboot,
link reconnect and any manager/driver reset. Do not treat a successful oneshot
start as evidence that the settings remain effective.

For service housekeeping, record effective units, dependencies, enable/mask
states, schedules and actual CPU/I/O/IRQ activity. Select only an unused,
observed component; preserve mDNS, management/access and required maintenance.
Any rescheduling must account for missed-run catch-up and randomisation,
security-update timeliness, mail/reporting and peer availability. Capture
exact restoration and repeat affected service/network acceptance.

For memory tuning, inspect `/proc/swaps`, swap priorities, zram configuration
and backing devices, memory-pressure/paging/OOM records and actual disk I/O.
The retained package list is not proof of active swap topology. Include build
and maintenance peaks in the comparison; do not change memory protection from
RAM capacity alone. Reconcile the observed distribution generator/profile
before rendering persistent changes, and verify reboot state and recovery.

Audio/boot and panic-reboot policies follow their own approved hardware or
recovery transaction. Capture existing settings, boot/access checks and
restoration. Preserve crash evidence and a manual boot-loop recovery route;
do not induce a production panic as a performance test. Keep adopted settings
and their installer/acceptance/recovery inputs in the repo, with live outcomes
in HISTORY.

### Public NTS upstream selection

[OPT-007](ntp-architecture-deployment-plan-v1.0.md#opt-007-public-nts-upstreams-for-arlington-texas)
owns the Arlington candidate shortlist. Provider documentation was checked on
October 12, 2026; none of these associations has been accepted on the rebuilt
node. Keep public-service names in the repo, with actual DNS addresses, paths
and capture results in bounded private evidence. Do not pin a sampled anycast
IP or infer the serving data centre from the certificate or hostname.

Candidate syntax for the pinned NTPsec client is:

```conf
server time.cloudflare.com nts
server ohio.time.system76.com nts
server oregon.time.system76.com nts
```

This is a review example, not an installed host profile. Render the selected
subset and poll/source-selection options alongside observed GPS/PPS, drift,
leap and restriction settings into the approved `/etc/ntp.conf` transaction.
Resolve operator/path/reference diversity before accepting the final set.
Keep normal TLS hostname, chain and validity checks; verify trusted CAs and
sane initial RTC/system time instead of adding `noval`.

Prepare one scoped upstream trial per node with exact candidates, address
families, sampling window/rate, egress checks, acceptance and restoration.
Verify DNS and TCP 4460 NTS-KE, then the negotiated NTP destination and UDP
port. Confirm the node's requests are not redirected back to local NTP by the
network interception policy. Review firewall changes in homelab-network.
Protect raw logs/captures and avoid collecting key material.

Use the pinned daemon's certificate/NTS-KE journal, association data,
`ntpq -pn` and `ntpq -c ntsinfo` with bounded peerstats/client observations.
Correlate authentication counters with each association; aggregate counters
alone do not prove all candidates work. Check authenticated responses and
renewal/recovery, not only TLS connectivity. Keep TLS setup duration separate
from NTP packet delay because key exchange is not performed for every sample.

Compare candidates under the same GPS/PPS discipline, poll profile and capture
windows, including peak/off-peak network load. Record NTP delay distributions,
offset/jitter, root distance/dispersion, loss, leap state and availability.
Verify supported address families and time-service behavior during approved
GPS/PPS or upstream-loss scenarios. Reuse OPT-004 plotting; do not conflate
smaller RTT with independently proven UTC accuracy.

After selection, check in the exact rendered host configuration and desired
upstream/poll/authentication policy as installation inputs. Record accepted
measurements in HISTORY and recheck provider policy, certificate/DNS health,
path quality and source diversity during routine maintenance. No live probe,
configuration or restart is authorised by this documentation.

## Leapfile, monitoring and routine maintenance

ntpleapfetch.service.in is intentionally unresolved until the installed command,
options, source URL, leapfile path/metadata, retry and reload behavior are
verified. The timer implements the architecture's four-week schedule. Render
the exact command, validate service/timer and approve installation/run before
activation. Do not add an ntpd restart without selected-build evidence.

Webmin needs explicit repository/key/package provenance, scope and authenticated
management acceptance. It is not fetched as an unreviewed extra repository by
the current assets tool. Munin endpoint/plugin configuration is owned by
homelab-monitoring-observability; approve intended poller/allowlist and prove
polling. Watchdog requires observed device/driver, independent recovery and a
separately authorized failure/reboot test. Hardware tools being installed do
not authorize I2C probing, thermal stress or sensor/firmware changes.

Routine checks cover both processes, GPS/PPS selection, reach/leap/stratum,
offset/jitter, dual-stack service/listeners and client responses, NTS/upstreams,
leap expiry, logs, storage, power/fan/temperature, monitoring and notifications.
Maintain the architecture's independent-node design and manual DNAT switching;
verify one active and one standby rule per address family. Preserve RA/global
IPv6 and static DNS VIP ownership through reboot and updates. Do not claim
controller GET data proves NAT state when that API omits the relevant rules.

For an update, review stable source/security changes, update explicit pins and
dependencies, build/test a new unprivileged candidate with clockmaker update,
compare old/new manifests, preserve live configuration and reviewed rollback,
then approve one node's install/cutover/acceptance. Repeat hardware/time/network
checks. Do not change PPS, regenerate ntp.conf or reboot as an automatic update
side effect. Preserve primary-supplied shared antenna power during outages.

## Recovery, records and validation

Old-card recovery restores the original Debian 11 hostname/configuration; it
does not reverse a hardware replacement. Verify physical target/card, access,
GPS/PPS and primary/antenna continuity before any outage. Stop if independent
recovery or antenna-power continuity is unresolved. Failures remain held until
terminal/partial state is inspected and an exact recovery action is reviewed.

Keep one history with accepted state, decisions and next gate, not a retry
transcript. Bundle-local review/specification/manifests and immutable accepted
receipts are necessary evidence assets, not additional active runbooks.
Current evidence carries integrity/provenance; historical claims cannot be
reset. Before pruning, verify dependencies and carry unique facts into the
current catalog/recipe or a required accepted provenance record. Ask when a
unique artifact's value is uncertain; do not delete it merely by age/name.

Offline verification from the repository root:

```bash
ntpsec/tests/run.sh
pre-commit run --all-files
git diff --check
gitleaks detect --source . --no-git --redact --no-banner
```

Keep regression fixtures for rejected parser formats, dependencies, protocol
selection, isolated imports, rollback and exclusive claims. They prevent
recurrence; they are not historical operation runbooks. Check local links,
rendered unit syntax and changed-shell Bash/ShellCheck/shfmt policy. Offline
fixtures and retained observations do not establish new live acceptance.

## Held hardware registry inspection

`run-host-registry-inspection.py` prepares one read-only diagnostic capture
against the exact executed hardware bundle and its recovered-file receipt.
`host-registry-inspection-20261013-v1` was executed, accepted and cleaned on
October 13. Its private report proves that only the loopback UUID changed
across reboot; the Ethernet UUID/type registry remained exact. The source hardware archive and root stage stay unchanged.

The capture reads the retained command journal and before/state records, current
boot identity and boot files, NetworkManager profile UUIDs/types and public
settings, active profiles, addresses and routes. A shared operation lock plus
end-of-capture checks detect concurrent changes. Profiles are observed without
normalizing away differences. No receiver/device access, profile changes,
service changes or reboot are included. Only the separate protected diagnostic
stage is created; conditional cleanup removes that stage after local acceptance
of its exact terminal report. Interrupted captures remain held for review.

Use the checked-in controller's `seal` command with `--hardware-dir`,
`--hardware-sha256`, `--operation-id` and a new `--output` directory. Approved
execution uses `execute --bundle ... --sha256 ... --mode capture` once;
conditional modes are `readback` and `cleanup`. Every mode is registered before
SSH. Capture or cleanup uncertainty never authorizes replay. Diagnostic
acceptance establishes evidence completeness, not hardware or network health.
The resulting recovery continuation was executed, accepted and cleaned on October 13.

## Recovery after loopback UUID drift

`host-recovery-continuation-20261013-v1` completed one recovery reboot,
acceptance through both pinned management endpoints and transient cleanup on
October 13. It binds the accepted inspection, its cleanup, the executed
hardware archive and diagnosed boot. Its execution modes are consumed.
`run-host-recovery-continuation.py` reuses the sealed original worker with
an in-memory registry comparison adapter. It permits only one loopback UUID
replacement whose public settings match the observed `lo` profile, manual
127.0.0.1/8 and ::1/128, empty gateways and autoconnect disabled. Every
non-loopback UUID/type and all existing Ethernet, dual-stack, DNS, route,
HTTPS, package/native/service checks remain binding. No profile is rewritten.

After separate approval and a console-ready declaration, `execute --bundle ...
--sha256 ... --mode reboot --console-ready` permits one recovery reboot from
the exact diagnosed state. It verifies the restored original boot bytes and
ownership/modes before submission. Then `--mode verify` checks the new boot
and both pinned endpoints before one acceptance. Conditional `--mode readback`
can use either endpoint; `--mode cleanup` stops only original operation reboot
transients. Both root stages and local evidence remain retained. A lost reboot
response never authorizes replay. Console/media recovery remains required if
SSH or boot fails; no second reboot is included.

Recovery acceptance restores the pre-hardware boot configuration; it does not
accept UART/PPS/RTC metadata or authorize runtime/account activation. Future
hardware/reboot stages must incorporate this tested, constrained comparison
and receive fresh approval instead of replaying the original consumed modes.

## Fresh post-recovery baseline and replacement hardware stage

`host-baseline-20261013-v1` is prepared offline for separate capture approval.
The existing registry inspector's `seal-baseline` command takes the accepted
recovery directory and exact bundle hash. It binds that recovery's receipt,
cleanup, current boot, original hardware source and retained protected stages.
It captures current package/service/Python observations, installed native files
and parent identities, boot/time/loader files, account identifiers, device
metadata, network profiles and static ELF dependencies. Capture makes no
application imports, device accesses or configuration changes. Only its new
protected diagnostic stage is created; conditional readback and cleanup follow
the existing single-use transport and terminal-hash rules.

The resulting `baseline.json` is new evidence. Historical installation,
networking and recovery records retain their original boot IDs and bytes.
Across the accepted reboot, only boot ID and service PID/restart counters may
differ from the old observation; other package/native/service or protected
configuration drift holds the capture. Acceptance checks bind the new boot to
the completed recovery receipt and require stable observations during capture.

After capture acceptance and cleanup, use `run-host-configuration.py seal`
with required `--baseline-dir` and `--baseline-sha256`, plus the existing
network provenance and target/kind arguments. Schema 2 binds the fresh baseline
hash, receipt and cleanup independently from the historical network receipt.
Both replacement hardware and conditional runtime bundles must bind the same
fresh baseline. The corrected hardware checker uses the constrained loopback
comparison directly; original networking mutation checks remain strict.
Do not seal or execute a replacement from the old pre-reboot baseline. The
new hardware/boot mutation bundle remains unsealed until fresh capture data is
accepted, and requires separate execution approval afterward.
