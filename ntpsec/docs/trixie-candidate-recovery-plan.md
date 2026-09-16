# Trixie candidate and recovery plan: j1-svntp1

Status: repository planning only, `2026-09-16`. This document implements
[governing plan v1.3](ntp-architecture-deployment-plan-v1.0.md); it is not an
execution bundle or permission to write media, access nodes, install packages,
change services, alter wiring or reboot. The architecture remains unchanged.

## Inputs and limits

Use the [Phase 1 checklist](phase1-evidence-checklist.md) and
[baseline summary](baseline-j1-svntp1-20260916.md) as the evidence index.
The Debian 11 configuration archive is historical input, not a Trixie image.
Full Phase 1 acceptance remains open. Missing tools and unresolved observations
stay visible; do not rerun the broad collector merely to obtain a clean status.

| Input | Planning consequence |
| --- | --- |
| Pi 4B, observed revision c03114, approximately 4 GB RAM | Use the governing plan's Pi 4B arm64 image choice; record exact image/build at preparation |
| Uputronics GPS/RTC rev 5.9 (2020), observed rv3028 RTC | Match the revision and selected image's device support before specifying overlays, UART, baud or PPS GPIO |
| Working PoE HAT (2018), beneath GPS HAT; header-only connection | Retain hardware; prove fan, thermals, power and shared GPIO/I2C compatibility on Trixie |
| Shared L1G1A-STD antenna and two-output splitter; j1-svntp supplies power | Leave primary and antenna-power path running during first-node work; defer primary outage until power continuity is designed and verified |
| Custom NTPsec/GPSD launched through timeservice.service | Do not copy that launcher or source-built binaries into Trixie; discover target package units and ownership |
| IPv4 PPS selected, reach 377, stratum 1, leap 0; IPv6 loopback time response verified | Useful historical reference; external clients, sustained health and post-reboot behavior still require acceptance |
| Webmin, msmtp, munin-node and watchdog not installed; needrestart installed | Plan fresh application setup; only reviewed needrestart settings are migration inputs |
| Aaron, working-console history, spare SanDisk Max Endurance 128 GB and USB reader | Recovery resources reported available; physical target identity and actual recovery remain untested |

## Candidate artifact contract

Produce rendered configuration only after its target-specific inputs are known.
Do not substitute Debian 11 paths, default package assumptions or guessed values
for unresolved fields. Each future artifact must identify its evidence source,
owner/group/mode, installation destination, validation, backup and rollback.

| Candidate area | Required input before rendering | Acceptance and ownership |
| --- | --- | --- |
| Image and bootstrap | Exact official image release/build, integrity evidence, Imager version, spare-media identity, approved bootstrap account/key and connection method | Correct Pi/arm64 identity, unique host keys and machine identity; console access before network cutover |
| Network/resolver | Observed Trixie manager, interface/profile, resolver ownership; approved allocation and conflict checks | Apply addresses and DNS from the governing plan through the actual manager; verify RA/global IPv6 retention and DHCP/RA DNS resistance after updates and reboot; homelab-network owns allocation |
| Boot/GPS/RTC/PPS | Revision-specific board information and selected image support; actual UART/PPS/RTC devices and permissions | Correct GPS feed/fix, RTC sanity, sustained PPS, no fan/GPIO/I2C conflict; do not open devices or change clocks during passive discovery |
| GPSD | Installed build, supported transport, startup/socket activation, device access and selected NTP refclock interface | One intended GPSD instance, correct feed ownership and persistence; choose SHM or another supported interface from target evidence |
| NTPsec | Target build/manuals, unit/config paths, daemon user, refclock support, drift/leap paths and upstream policy review | One time daemon, GPS/PPS selection, reach/offset/jitter and leap health, IPv4/IPv6 client service, intended restrictions and NTS behavior |
| Leap maintenance | Actual ntpleapfetch path/options/source, file validation and daemon reload behavior | Implement the governing four-week schedule; verify timer and successful maintenance under later authorization; no assumed restart |
| Webmin | Approved repository/key provenance, target package, management access scope | Authenticated management test and no unintended exposure; no legacy settings to copy |
| needrestart and mail | Reviewed common baseline policy, target versions, Mailrise endpoint and credential reference | Non-disruptive reporting and delivered test notification via msmtp/sendmail as required; no secret in Git |
| Munin | Approved poller, address families, allowlist and NTP plugin choices from Munin owner | Listener/allowlist and successful intended polling; Caddy-specific files are not an NTP template |
| Watchdog | Driver/device ownership, chosen userspace owner, mail path and proven recovery | No resets until recovery passes; separate controlled acceptance test and explicit rejection/disable path |
| Inventory | Per-node observed hardware/software/media and accepted addresses | Draft incomplete facts explicitly; finalize only after live acceptance in homelab-server-configs |

Keep the protected byte-exact Debian 11 ntp.conf capture separate from the
Trixie candidate. Review captured content for secrets before making an accepted
host-specific repository mirror. Do not label the historical capture as an
accepted Trixie configuration or modify the executed collector artifacts.

## Ordered preparation and authorization gates

1. **Close baseline review.** Classify remaining checklist items as required
   before first-node outage, target-discovery input, later acceptance, or
   second-node-only input. Resolve safety-critical gaps; record any explicitly
   accepted limitation rather than silently declaring Phase 1 complete.
2. **Define media preparation.** Select and record the exact image and its
   provenance, spare-card identity and reader mapping. Verify the write target
   against both old media and workstation disks. Reject ambiguous identity or
   a target containing the original Debian 11 installation. Prepare a concrete
   media-write specification; obtain separate authorization before any write.
3. **Define first-boot discovery and recovery.** The first boot of a replacement
   card is a maintenance action even if subsequent queries are read-only.
   Define failure-based stop conditions, bootstrap access and network behavior, permitted
   writes, evidence capture, stop conditions and old-card recovery. Verify the
   primary's client service and antenna-power path through separately scoped
   preflight. Do not introduce a duplicate node identity on a second device.
4. **Prepare the target from observed inputs.** If target package state requires
   installation or startup to discover, include that explicitly in its approved
   candidate-stage bundle; do not describe it as passive inspection. Collect
   actual versions/units/manuals, render and locally validate the candidate,
   then request the distinct configuration deployment scope. Aaron permits an
   unrestricted first-node outage; restore the old card on the defined failure
   conditions or his decision to stop, without inventing a time cutoff.
5. **Deploy and accept j1-svntp1.** Follow the governing Phase 3 sequence, with
   bounded validation, recovery and observation criteria in the final bundle.
   Do not promote DNAT simply to test the first rebuild. Retain the old card.
6. **Defer the primary.** Before its later maintenance, complete its own baseline,
   prove standby client service and design/verify antenna-power continuity.
   DNS and UniFi changes each retain their separate owner and authorization.

These gates separate what can be prepared offline from what requires a booted
Trixie target; an unknown target path must not become an executable placeholder.

## First-node recovery contract

Aaron is the named hands-on operator. The micro-HDMI KVM/laptop previously
worked with this node; reconfirm it at the approved maintenance preflight.
Aaron allows maintenance anytime with no fixed j1-svntp1 outage limit.
Use failure-based recovery, initiated by Aaron, rather than a discovery
deadline. Define bounded individual checks, acceptance thresholds and the
observation interval in the final bundle; unrestricted outage time does not
waive those gates or authorize execution.

Before removing the old card, establish the healthy primary/client baseline,
verify the protected configuration archive can be read and its hashes checked,
and match the original card to this node using the protected media identifiers
and operator labelling at the safe removal point. Keep it untouched and
physically separate from the spare. The archive is a configuration backup,
not a complete bootable disk image; the original card is the primary rollback.

| Trigger | Required response within the approved maintenance scope |
| --- | --- |
| Ambiguous card, no console, primary unhealthy or antenna path uncertain | Stop before writing media or powering down the node |
| Replacement does not boot or management cannot be recovered within the approved procedure | Preserve diagnostics, stop unapproved troubleshooting and invoke old-card recovery on the defined failure condition or Aaron's decision |
| GPS/PPS, power/fan, network/DNS or client acceptance fails | Preserve evidence and use the approved rollback; do not relax restrictions or improvise boot overlays to force acceptance |
| Watchdog reset loop during its later controlled test | Use its preapproved disable/recovery path; recover through console or old media if necessary |
| Physical HAT failure | Stop software-only recovery assumptions; PoE+ replacement requires its own compatibility and recovery scope |
| Old card fails to restore healthy service | Keep primary serving and its antenna path intact; stop and request scoped diagnosis, retaining failed evidence |

Old-card recovery sequence, to be executed only under the later approved bundle:

1. Preserve available failure output without delaying necessary recovery.
2. Power down only j1-svntp1 through the approved procedure. Leave primary,
   shared antenna, splitter and existing power arrangement undisturbed.
3. Aaron replaces the candidate card with this node's identified original
   Debian 11 card; retain the candidate for diagnosis without rewriting it.
4. Boot using the console and verify original hostname, release, media and
   network identity before relying on remote access. Verify SSH identity;
   do not bypass a host-key mismatch introduced by the new image.
5. Verify intended NTP/GPSD launcher, listeners, GPS/PPS selection, reach,
   stratum/leap and controlled-client time responses. Compare to the captured
   old baseline, not Trixie-only goals such as a new permanent ULA. Reconfirm
   primary service and record rollback success or failure separately.

A successful boot or SSH session alone does not demonstrate restored service.
A tested console history does not constitute an executed media-swap recovery.

## Evidence, validation and remaining decisions

Reuse `/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/`. Each future
operation must specify the minimum named output files, refuse overwriting
existing evidence, protect directories/files with owner-only permissions and
reject symlinks. Keep credentials out of transcripts and repository artifacts.
Do not create a directory per action or extract another copy of the baseline.
Retain exact executed source/bundle hash, transport and command statuses,
pre/post integrity checks where applicable, and failed results as well as passes.

Before a live proposal, validate its final artifacts with the applicable
Markdown/link/Git, secret, shell, offline rejection/success and unit checks.
Repeat target-dependent checks on Trixie. Define numeric acceptance thresholds
and the observation interval before execution; do not invent those from a
single Debian 11 peer snapshot. The old IPv6 control timeout does not justify
relaxing noquery; verify client service separately from management access.

The [image/media and bootstrap specification](image-media-bootstrap-spec.md)
is drafted; finish its pending operator inputs:
record a current official image selection, define operator-side spare-card
identity evidence, and select a controlled first-boot access method. That task
must resolve workstation/reader location, bootstrap account/key reference,
baseline gaps before proposing a write or outage. Maintenance timing is
already confirmed as unrestricted for j1-svntp1.
Do not request secrets in chat. No media write or live action is authorized by
this document, and no executable deployment bundle has been produced.
