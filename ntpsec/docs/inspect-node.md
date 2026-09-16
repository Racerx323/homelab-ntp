# Debian 11 baseline collection contract

Status: working-tree schema v3 fixes ntpq response validation and refclock
query selection; **not executed**. Executed v1/v2 artifacts remain in their
original archives. V2 integrity passed but its baseline remains incomplete.
See the [Phase 1 checklist and minimal probe proposal](phase1-evidence-checklist.md).
A full v3 collection is not proposed as the next live action. The full-collector
contract below is a reference for any separately scoped future use.
Target: `j1-svntp1` only. This implements the Phase 1 definition in the
[governing plan](ntp-architecture-deployment-plan-v1.0.md).

## Invocation and prerequisites

The single execution artifact is [inspect-node.sh](../scripts/inspect-node.sh).
It embeds its Python engine so the collector SHA-256 covers all execution
logic. No configuration is sourced or evaluated. The production entry point
has no fixture-root, command override, or alternate-target option.

Proposed invocation, after separate authorization and protected staging:

```bash
cd /var/tmp/ntp-baseline-stage-j1-svntp1-v3
/bin/bash ./inspect-node.sh --collect \
    --output /var/tmp/ntp-baseline-j1-svntp1-v3
```

Run as UID 0, using an authorized SSH account and noninteractive `sudo -n`
where necessary. Require `/bin/bash`, `/usr/bin/python3` (Debian 11 Python 3.9
or newer), the exact kernel hostname `j1-svntp1`, and `ID=debian` or
`ID=raspbian` with `VERSION_ID=11` in `/etc/os-release`. The collector rejects
other identities/releases before any collection or output-directory creation.
It parses release text as data. Duplicate release keys are rejected.

The output must be a **new** direct child of root-owned, sticky `/var/tmp`,
named `ntp-baseline-j1-svntp1-` followed by letters, digits, underscores or
hyphens. Existing paths, including symlinks, are rejected. Directory creation
is exclusive, with mode `0700`; files use `0600` through umask `077`.
Use sufficient free space for two manifests and byte-exact captures; the
per-file capture ceiling is 16 MiB. Oversize files remain errors.

Expected diagnostic tools are systemctl, journalctl, uname, lscpu, uptime,
findmnt, lsblk, dpkg-query, apt-cache, ip, ss,
ntpq, ipcs, ls, ps, lsmod, vcgencmd, nft, iptables-save and ip6tables-save.
Some alternatives will normally be absent on Debian 11. The collector does
not install them or silently treat them as successful. Commands use a fixed
system PATH, C locale, no pager, no input, and a 20-second timeout each.
There is no automatic retry. Systemd unit and association counts determine
total duration; this is not a fixed-duration health check.

## Read-only boundary

The only explicit writes are the approved staging and evidence files. Reads
can update access times, and SSH/sudo/local daemons can produce ordinary
audit logs or counters. The read-only assertion concerns configuration,
services, network state and boot media; it does not assert a bit-identical
running filesystem or suppress normal system activity.

- Query only local state and numeric loopback NTP endpoints `127.0.0.1` and
  `::1`, with `ntpq -n`. No upstream NTP queries, DNS queries, other-node
  connections, controller contact, mail delivery or external downloads.
- Read installed package metadata/cache without refreshing repositories;
  apt-cache disk cache output is disabled.
- Use systemctl list/show operations and bounded journal reads. Service-only
  `MainPID` and `NRestarts` properties are requested only for `.service` units.
- Inspect hardware through existing procfs/sysfs observations, device-link
  metadata and read-only firmware queries. Do not open serial, PPS, RTC or
  watchdog device nodes; do not probe I2C, stimulate GPSD, run Munin plugins,
  run needrestart, run ntpleapfetch, reload services, or write boot media.
- Read manager runtime files instead of invoking manager D-Bus clients that
  could activate an inactive service. Missing runtime state stays unknown.
- Never source configurations, run password helpers or execute captured
  scripts. `ps`, journals, network profiles and configuration content are
  potentially sensitive even when the command is read-only.

## Exact output contract: `ntp-baseline-v3`

Stdout is one JSON summary on a completed collection, containing `schema`,
`exit_status`, `collection_status`, `output`, and `baseline_accepted: false`.
Stderr contains preflight/abort diagnostics. Neither stream deliberately
prints captured configuration. Retain both as protected data regardless.

| Relative path | Contract |
| --- | --- |
| `INCOMPLETE.json` | Schema and start time; remains on interruption/abort; removed only after the final report is written |
| `commands.json` | Ordered array; each entry has label, exact argv, numeric exit status, response_error (null or diagnostic reason), stdout path and stderr path; updated after every command |
| `commands/NNN-LABEL.stdout` | Raw stdout bytes, including partial output from failures/timeouts |
| `commands/NNN-LABEL.stderr` | Raw stderr bytes; timeout diagnostic appended on timeout |
| `protected-before.json` | Path-keyed pre-state records, including UID/GID, mode, size, mtime, file SHA-256 and capture path, or explicit absent/error/type/link state |
| `captures/SHA256` | Byte-exact pre-state regular-file data, deduplicated by content hash; restore filenames through the manifest, never by guessing |
| `protected-after.json` | Re-enumerated post-state records and hashes, without capture references |
| `passive-files.json` | Path/pattern-keyed procfs/sysfs observations; NULs are JSON-escaped, absent/error states retained; not included in stable configuration comparisons |
| `leapfiles.json` | Captured leapfile candidates and referenced leapfiles, SHA-256, parsed `#@` UTC expiration and expired/not-expired/unknown/invalid state; validity remains pending installed-build review |
| `executables.json` | All six ntpq candidates, absent/rejected/trusted states and the unique selected absolute path; no guessed fallback |
| `startup-before.json`, `startup-after.json` | NTP/GPSD process executable links, cmdline, status, cgroup and bounded parent ancestry; disappearing/reused PIDs remain errors |
| `integrity.json` | Protected differences and separately recorded resolver runtime mtime changes |
| `report.json` | Schema, target, finish time, collection status, exit status, protected comparison result, issues, operator confirmations and evidence-review requirements; baseline acceptance is always false |

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Collection completed with equal protected manifests and no collection errors; does **not** accept the baseline |
| `2` | Collection completed with missing/failed commands, unsupported references, unreadable captures or other issues; also argparse usage errors before output creation |
| `3` | Protected path set, metadata, links or content changed; retain evidence and investigate, never restore automatically |
| `64` | Identity, privilege, release, destination or destination-creation gate rejected |
| `1` | Unexpected collection abort; partial evidence remains |
| `130` | Python caught interruption; partial evidence remains |

Transport failures, missing interpreter, unhandled signals and shell startup
failures can have other statuses. A zero SSH status alone is insufficient:
require a complete report, no incomplete marker, matching collector and
transport statuses, and review of all absent/error states. Expected absence
is still an observation to review, not proof a requirement was met. Failed
commands normally make the collection incomplete even when an alternative
firewall or firmware tool is simply not installed.

## Evidence coverage and limits

| Area | Collected evidence and unresolved facts |
| --- | --- |
| Host/media | Kernel hostname gate, hostname/machine ID/release captures, boot ID/time, CPU/revision/RAM, mounts, block capacity/type/filesystem/UUID/PARTUUID/serial and MMC CID; physical card label and independent recovery require operator confirmation |
| Pi and HATs | Device-tree model/serial/HAT data, kernel/modules/journal, firmware and bootloader queries, boot configs, RTC/I2C driver names and time, PPS assertions, fan/thermal and undervoltage evidence; board model/revision, antenna wiring, stack order, physical switch port and actual power class/budget require operator confirmation |
| Network/DNS | Addresses/routes/rules, local manager units, NetworkManager device/runtime profile files, networkd link/lease and resolved runtime files, interface/DHCP/manager profiles, resolv.conf link target and bytes; review effective ownership and DHCP/RA behavior without querying DNS; authoritative network/DNS repositories remain separate |
| NTP/GPSD | Config/defaults, discovered unit fragments/drop-ins/start arguments/users, process list, local IPv4/IPv6 listeners, peers, system variables, association-specific peer/clock variables, SHM metadata, GPSD state and passive PPS data; no active GPS fix or pulse qualification |
| Leap maintenance | Source scripts, configs, cron/unit/timer definitions, packaged manuals, leapfile references/bytes/modes/hashes and expiration; historical manual command/source URL/success/status require corroboration, and authenticity/reload behavior require installed-build review; never execute ntpleapfetch |
| Baseline apps | Installed package versions and cached origins, local accounts/groups, unit state/journals, Webmin core settings/source version, needrestart policy, system/root msmtp config and aliases, Munin config/allowlist/plugin links and listeners, watchdog policy/driver state; no authenticated login, delivery, polling or watchdog reset test |

The script's `CONFIG` tuple is the exact initial protected path/glob list.
It includes local systemd definitions, network and application directories,
boot configuration, package sources, packaged NTP documentation and selected
leapfile/source-script locations. Traversal records every directory and link;
regular files receive content hashes and byte captures. Symlink targets under
`/etc`, `/run`, `/usr`, `/lib`, `/var/lib` and `/boot` are followed explicitly;
`/dev/null` unit masks are recorded without opening the device. Other targets
are reported out of scope. Special files are never opened for capture.

Discovered relevant unit fragments/drop-ins and absolute NTP `includefile`
and `leapfile` references under `/etc`, `/var/lib` or `/usr/share` extend that
set. Relative, ambiguous and unsupported references remain errors. Executable and process discovery plus initial
unit discovery precede the pre-snapshot; discovery is repeated before the
post-snapshot. Hashes cover the subsequent diagnostic interval, not the SSH
login/staging interval. Comparison excludes atime, volatile telemetry and the
pre-state capture filename, but includes protected path membership and
metadata. The sole additional exclusion in v2 is `mtime_ns` for regular
files and directories at `/run/resolvconf` and below. Both original timestamps
remain in the manifests and `integrity.json`; content, size, UID/GID, mode,
links, type and path membership still fail the protected check when changed.
Persistent `/etc/resolv.conf` timestamps are not exempt. An equal comparison with unreadable files does not verify their
contents; errors still prevent a successful collection result.

Alternative installations, boot include files, per-user mail configuration,
custom scripts, environment files outside captured directories and command
line overrides require review. Discovering an unsupported path does not
authorize another collection or justify declaring inventory complete.
Leapfile expiration uses the observed host clock; it does not prove clock
correctness, file authenticity or NTPsec acceptance.

## Protected handling and proposed single authorization

Raw output may contain credentials, private keys embedded in service files,
mail passwords, network secrets, precise GPS data or private infrastructure
details. Keep the **entire** evidence set outside every Git worktree, with
root-only remote access and owner-only local access. Do not attach raw output
to chats, issues, external review tools or CI. Retain original captures intact
and create separate reviewed, redacted summaries for repository history.
An accepted `/etc/ntp.conf` mirror is a later reviewed action.

Use the existing persistent workstation directory
`/home/aaron/code/.local-evidence/homelab-ntp/j1-svntp1/`.
**Do not create a new local directory for each action.** The future full-collector run
uses only these exclusively created, operator-owned `0600` files there:

- `baseline-v3.tar`: protected remote output, exact executed collector,
  collector status and per-file transfer hashes in one archive.
- `baseline-v3.stdout` and `baseline-v3.stderr`: collection transport streams.
- `baseline-v3.status.json`: exact command/hash, collection and retrieval SSH
  statuses, collector status, transfer diagnostics and verification result.

Validate existing directory ownership, `0700` permissions and absence of
symlink components before writing. Use umask `077`; reject occupied output
filenames instead of overwriting them. Verify archive members and hashes
without extracting a duplicate local directory tree. Preserve failed/partial
files under those same names. Do not create extra logs, copied scripts,
per-action directories or parallel unpacked archives. The executed script is
retained inside the archive; repository history holds the sanitized outcome.

Existing v1 archives are preserved intact. This preference does not authorize
deleting original evidence. Local `/tmp` and `/var/tmp` are not retained
evidence locations. The fresh `/var/tmp` paths in the invocation are on the
NTP node, where exclusive staging/output creation remains required. No remote
cleanup is authorized; it can be scoped after archive verification and review.

Any future full-collector authorization must cover its final SHA-256 and:

1. SSH as `ama` to `j1-svntp1` at the plan's numeric address `10.1.0.51`
   (FQDN `ntp1.local.theama.co`), using existing trusted SSH host keys.
   Disable connection multiplexing for this operation; no new trust enrollment
   or interactive password/privilege prompt. Stop on trust/access failure.
2. Stage only the hash-matching script in a new root-owned `0700`
   `/var/tmp/ntp-baseline-stage-j1-svntp1-v3` directory, as a root-owned `0600`
   regular file; reject existing paths/symlinks. Verify remote SHA-256 before
   invocation. No executable installation or service change.
3. Run the exact command above as root from the stated directory, once.
   Capture command stdout, stderr, collector status and SSH transport status
   separately into the named files in the existing workstation directory. Use a
   remote shell wrapper that records the collector exit status independently;
   absence of that record means the collector result is unknown.
4. Retrieve the protected evidence as `baseline-v3.tar` over the same SSH
   connection scope. Verify member hashes without extracting it; record
   transport/collector statuses and verification in `baseline-v3.status.json`. Retain partial evidence on every failure.
   Review the report, original errors, captures and pre/post comparison.

This authorization permits only the named staging/evidence writes and local
read-only diagnostics, including loopback NTP queries. It excludes cleanup,
automatic retry, remediation, imaging, another node, UniFi, DNS services,
ntpleapfetch execution and any service/network/boot change. No configuration
rollback is performed because no configuration mutation is authorized. A
detected difference or interruption requires evidence review and a new gate,
not an automatic restore or rerun. Keep staging and evidence for review;
cleanup can be scoped later. An edit to the collector requires a new hash and
authorization.

## Deployment guide and observed startup

The user identified the [NTPsec Stratum-1 Microserver HOWTO](https://www.ntpsec.org/white-papers/stratum-1-microserver-howto/)
as the original deployment guide. It describes a source-built installation
and a `timeservice.service` wrapper around `/etc/init.d/timeservice`.

Local review of the existing archive confirms an enabled, active/exited
`timeservice.service`, `Type=oneshot`, `RemainAfterExit=yes`, and an
`ExecStart` pointing to `/etc/init.d/timeservice start`. This establishes the
configured launcher; procfs/cgroup evidence and the actual init script are
still needed to complete the process-ownership review.

V2 explicitly selects `timeservice` units and captures the init script, udev
rules, `pinup` and cpufreq policy where present, without executing them. The
guide is historical context, not a Trixie recipe or proof of hardware wiring.

## Follow-up discovery boundaries

Before queries, inspect ntpq at `/usr/bin`, `/usr/sbin`, `/bin`, `/sbin`,
`/usr/local/bin` and `/usr/local/sbin`. Require exactly one distinct resolved
executable with root-owned, non-group/world-writable file and ancestors.
Record all candidates, resolve aliases, hash/capture the selected file and
invoke only its absolute path. Missing, unsafe or ambiguous candidates produce
explicit errors and query status `127`; no package installation or automatic
alternative execution occurs. Other missing diagnostic tools retain their
original failures. The ordinary subprocess PATH remains unchanged.

Read procfs entries whose `comm` is `ntpd` or `gpsd`, plus up to eight parent
levels. Record executable link, argv bytes, status and cgroup; compare process
starttime within each observation to detect PID reuse. Inspect identified
cgroup service definitions even when their names do not contain NTP/GPS.
Capture `/etc/rc.local`, SysV init scripts/runlevel links, root crontab,
supervisor definitions and local NTP/GPSD configuration/manual paths as
additional startup evidence. Do not execute any startup script. Detached or
reparented processes may still require operator/source review; ancestry alone
does not prove the historical launch mechanism.

A `FragmentPath=/dev/null` is a recorded systemd mask, never a device to open.
Its raw unit definition and captured mask link remain evidence. Capture all
other unresolved paths as errors. None of these changes reclassify the v1
result or authorize a service change.

## V3 NTP response handling

Ntpq may return zero after a protocol failure. Preserve its process status and
both streams; also record `response_error` and mark the collection incomplete
on empty output, nonempty diagnostic stderr or recognized protocol-error text.
Only a successful, matching association reply with one numeric `srcadr` can
classify a refclock. Send `cv` only for `127.127.0.0/16`; never infer a local
refclock from `refid=PPS`. Classification failures remain issues.

The minimal IPv6 time probe has its own output and privilege contract in the
[Phase 1 checklist](phase1-evidence-checklist.md); it does not run this collector.

## Offline verification

Run `ntpsec/tests/run.sh`. It extracts the embedded engine without invoking
the collector entry point on the workstation, uses temporary synthetic
filesystems and stubbed commands, and performs no network activity or live
node collection. The same test path runs in pre-commit and CI. Shell syntax,
ShellCheck, shfmt, documentation/YAML/workflow lint, a full working-tree secret
scan and Git checks supplement the fixtures. Offline success does not prove
Debian 11 command availability or live hardware/service acceptance.
