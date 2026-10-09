# First boot and recovery authorization proposal

Target: physical j1-svntp1 at its original 10.1.0.51, rebuilding as j2-svntp1.
Status: preflight accepted on October 8; execution HOLD pending separate
approval of this exact bundle. See the
[preflight results](pre-rebuild-results-20261008.md).
No current primary health, accepted client impact or first-boot success is
inferred from the media write. Media write and 100% verification are complete.

## Preconditions and scope

Aaron performs all physical actions and console commands. No autonomous SSH
shutdown, controller mutation or power-port cycling is included. Preserve
j1-svntp, shared antenna power, splitter wiring and the working PoE HAT.
Only the rebuilding node may be powered down. Maintenance can occur anytime
and has no fixed outage limit; failure-based recovery remains mandatory.

Before shutdown record the accepted R1/R2/R3 results and client-impact decision,
verify KVM access and the protected old archive's recorded hashes, and visually
identify the old/new media. If any condition is missing, stop before shutdown.
The original card stays untouched as rollback; it is not replaced by a config
archive. New card: verified October 6 Trixie Lite arm64 image, Imager 2.0.12,
j2-svntp1, ama, password SSH, Ethernet DHCP, US keyboard/America Chicago.
Do not assume Wi-Fi is disabled merely because no wireless credentials exist.

## Bound preflight and recovery readiness

R1's strict-host-key retry passed with primary PPS selected, reach 377,
stratum 1 and leap 00. R3 returned valid synchronized responses from both
servers. R2 established that DHCP advertises both servers. R2b's rule details
and complete 36-record operator list establish the source-limited IPv4
translation to 10.1.0.50:123 with no displayed competing Destination NAT rule.
No standby DNAT rule is shown; preparing one remains later network-policy
work before the primary-rebuild transition, outside this operation.

Aaron accepted possible temporary time-sync loss on unidentified clients.
These results do not establish universal client failover or forwarded packet
traversal. They are retained October 8 observations, not continuous monitoring.
Aaron confirmed KVM readiness, old-card preservation and unchanged primary
power/shared antenna/splitter wiring for this maintenance checkpoint. Stop
before shutdown if any of those conditions changes.

The retained baseline-v2.tar hash matches its recorded value:
`fd4d4c7ec1b900bb41ef3e843f9340dee2e6b5fb660a4b7948f646a32d79b764`.
Its historical baseline remains unaccepted; this verifies preservation of the
archive and does not replace the original-card rollback path. The bundled
preflight-reference.json binds the retained evidence and immutable approved
preflight bundles by hash. No new primary/client/controller query is needed
to assemble this proposal.

## Operator sequence and exact commands

Run at the current node's KVM console, not on primary or the workstation:

```sh
hostname
cat /etc/os-release
```

Require original hostname j1-svntp1 and Debian 11; otherwise stop. Once all
preconditions pass and this operation is separately approved, Aaron executes:

```sh
sudo /sbin/shutdown -h now
```

Wait for completed halt using the console. Aaron safely removes power from
only that Pi, removes and labels its original card, inserts the verified spare
and restores power. Do not swap a card while powered. Boot customization,
DHCP, journaling and factory-enabled services are permitted normal image
side effects; first boot is not a read-only operation.

Aaron finds the DHCP IPv4 address through UniFi, with KVM fallback. On the new
node's console log in as ama and run this bounded inspection, retaining output:

```sh
hostname
cat /etc/os-release
uname -m
uname -r
findmnt -n -o SOURCE,FSTYPE /
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT
ip -brief address
ip route show
ip -6 route show
systemctl --no-pager --failed
systemctl --no-pager is-active ssh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Each inspection command is allowed at most 15 seconds before Aaron interrupts
it and records an error. Missing utilities/files are unresolved, not reasons
to install or improvise. Do not print passwords or private host keys. Record
DHCP address/interface and fingerprint; neither is known before this boot.
Verify hostname j2-svntp1, Debian 13/Trixie, aarch64, expected replacement media,
usable console and Ethernet address, and no unexpected failed service. Check
fan operation and power/thermal symptoms by console/physical observation;
full HAT and sensor validation remains later, not implied by a successful boot.

Aaron may open one password SSH session as ama to the observed DHCP address,
only after comparing the server's fingerprint with console evidence. Keep KVM
available; never bypass host-key mismatch or delete unrelated trust entries.
Confirm hostname and release in that session, then stop. No agent password
collection and no pre-pinned unknown DHCP target are included.

No security updates, package installations, static addressing, Wi-Fi driver
changes, SSH-key installation, NTP/GPSD configuration, DNS edits or DNAT changes
are authorized in this first-boot step. Define those later from target evidence.
No GPS/PPS/NTP acceptance is required of the unconfigured new image, and no
service replacement success is claimed; primary remains responsible for time.

## Rejection and rollback

On wrong identity/media, unusable console/SSH, boot loop, unsafe fan/power
behavior, primary service degradation or Aaron's decision, stop and recover.
Record available diagnostics. If the new OS is responsive, use the same
sudo /sbin/shutdown -h now command at its verified console. If it cannot halt,
Aaron may remove only this node's power as a last-resort recovery action;
record that action and possible candidate-media corruption. Preserve primary.

With power removed, reinstall the labelled original Debian 11 card, retain
the spare unchanged for diagnosis, and boot the original system. Verify old
hostname j1-svntp1, Debian 11, original root media and 10.1.0.51. Verify original
SSH fingerprint against baseline or console before reconnecting. Do not infer
success from boot/SSH alone. The archived standby baseline records /usr/local/bin/ntpq;
run these bounded queries on the restored original card:

```sh
/usr/local/bin/ntpq -n -c 'rv 0 leap,stratum,peer,offset,rootdisp' 127.0.0.1
/usr/local/bin/ntpq -n -c peers 127.0.0.1
```

Require successful semantic responses, original PPS selection and leap 00/
stratum 1, and review reach/quality against the old baseline. Then run the
bundled pre-rebuild-health.sh --client-ipv4 on the approved workstation (one
request each to .50 and .51, unchanged R3 contract) to verify restored direct
client service and surviving primary. This bounded rollback-only probe is
part of the proposed rebuild authorization, not reuse of an exhausted R3 run.
Do not run the primary-host mode on the standby. Missing historical ntpq path
or failed service recovery holds further changes and requires scoped diagnosis.

## Evidence and authorization boundary

Record one protected first-boot-result.json (or equivalent operator transcript)
in the existing host evidence directory: bundle hash, preflight references,
operator/timestamps, old/new identity, commands/statuses, DHCP/fingerprint,
media actions, errors, final state and rollback results. Do not overwrite old
evidence or create another evidence tree. No cleanup, second attempt after
an interrupted mutation, or primary outage is included.

The final bundle includes the accepted preflight/client-impact results,
operator readiness and preserved archive verification. The historical rollback
ntpq path is specified above. Any scope/content change requires a new bundle
hash and approval. Preparation does not authorize execution.
