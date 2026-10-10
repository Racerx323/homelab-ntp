# Trixie installation inputs: read-only proposal

Prepared October 9, 2026. Preparation is authorized; execution awaits approval
of the exact bundle hash. Target only non-root `ama@10.1.0.137` (`j2-svntp1`).
The required console-verified ED25519 fingerprint is
`SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys`.

## Coverage against the governing plan

The [per-node baseline](ntp-architecture-deployment-plan-v1.0.md#per-node-baseline-and-acceptance)
requires more than needrestart. This proposal inventories every named package
component plus notification prerequisites and the dependencies declared by the
locally reviewed needrestart 3.11-1 archive. Package names are queries, not an
approved installation manifest.

| Requirement | Inputs in this proposal | Acceptance still required later |
| --- | --- | --- |
| Base OS/access and package provenance | Identity, native/foreign architectures, OS/kernel/SSH/firmware package status, sources, preferences, keyring metadata/hashes, APT policy and timers | Fresh signed metadata, reviewed exact package resolution, administrative/recovery readiness and update/reboot acceptance |
| needrestart | Package and declared dependency status; cached candidates/direct dependencies; configuration, hooks, Pi-fragment owner and boot-image metadata | Trusted complete dependency closure, enabled kernel checks, list-only reporting and actual kernel/service reports |
| msmtp/sendmail and cron | Package status, sendmail owner/link, msmtprc metadata and readable allowlisted fields, reporting job/crontab and cron unit | Protected complete relay policy, exact recipient/schedule and authorized Mailrise delivery acceptance |
| Webmin | Package status/cached metadata and unit state | Provenance, reviewed settings, authenticated LAN management and exposure checks |
| Munin | munin-node package/cached metadata and unit state | Component-owned configuration, listener/allowlist and poller collection over intended address families |
| Watchdog | Package/cached metadata and unit state | Driver/owner, reviewed configuration, independent recovery and separately approved controlled test |
| NTP/GPS/RTC/PPS and PoE HAT | ntpsec, gpsd, gpsd-clients, pps-tools, i2c-tools and firmware/support package status/cached metadata; running kernel and boot-image names | Actual devices, overlays, RTC/PPS/fix, fan/power/thermal behavior, daemon policy, leap timer and dual-stack NTP acceptance |
| Networking and DNS | Existing inspection remains the observed reference; relevant OS/network packages are inventoried | Fixed NetworkManager profile, addresses/DNS, routing, exposure and reboot persistence in their own stages |

No read-only snapshot proves all installation dependencies or baseline
requirements. Cached direct dependencies omit fresh solver decisions, version
constraints, selected alternatives, transitive closure and enabled recommends.
Keyring hashes identify files; they do not capture public keys or prove archive
signatures. Required custom key paths and includes must be reviewed from the
captured sources/configuration. Resolve these gaps before installation approval.

## Exact collection scope

The bundled collector runs `--installation-inputs`. It rejects the wrong host,
OS, architecture or root identity before invoking any child command. It uses
the existing six package-policy queries and eight additional queries:
native/foreign dpkg architectures, baseline package status, cached APT policy,
cached direct dependencies, Pi-fragment owner, sendmail owner and reporting-unit
state. `apt-cache` disables both cache output paths. No recursive solver,
metadata refresh, package download/install/simulation or hook invocation runs.

Capture policy/source/listchanges/dpkg files as data, with credential redaction,
at most 160 paths and 64 KiB per file. Reject symlinks/nonregular files. Never
evaluate Perl, shell, configuration includes or passwordeval. Capture at most
128 metadata paths covering standard public-keyring locations, boot kernel
images, sendmail, aliases and msmtprc. Hash only the designated keyring files in
this metadata group. Do not capture aliases content or hash msmtprc credentials;
msmtprc exposes only allowlisted account fields when readable. Other directives
are marked omitted. Permission failures remain gaps; no sudo fallback occurs.

Compare policy inputs and metadata before/after collection and verify unchanged
boot ID. Retain missing packages, unavailable tools, unreadable inputs, redaction,
truncation and drift. Exit 0 indicates collection without detected query gaps;
it never accepts package trust, effective policy, relay behavior or installation.
Exit 2 preserves gaps; exit 1 or a missing terminal marker is incomplete.

Each child query has a 12-second timeout and 64 KiB stdout/stderr limits. The
transport has a 240-second timeout with a five-second termination allowance.
Use the bundled pinned known-host entry, strict ED25519 verification, batch
authentication and no password prompt, proxy, connection reuse, forwarding or
local command. Invoke the bundled stdin payload through `cd / && /bin/bash -s`.
The private approval manifest records the exact workstation transport argv.

## Mutation and recovery boundary

No primary-node/controller/DNS access, remote staging, sudo, package or timer
change, service activation/restart, reboot, notification wrapper, SMTP probe or
mail is permitted. Normal read-only command activity may occur. This proposal
does not authorize installation or notification acceptance.

Immediately before an approved submission, verify the archive, every member,
payload and pinned host-key fingerprint. Register the invocation before
submission; retain stdout, stderr and transport/collector status separately in
the existing owner-private evidence directory. Do not overwrite evidence or
resubmit after interruption without recovering the original terminal state.

No configuration rollback is needed for this collection. On failure or drift,
retain evidence and hold mutation. The original Debian 11 card remains the
future installation recovery boundary; primary power and antenna wiring remain
untouched. After review, prepare fresh trusted metadata/package resolution and
the exact policy/installation bundle with permitted hooks, acceptance and
old-card rollback before requesting that stage's execution approval.
