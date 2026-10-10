# Trixie package stage: policy preflight and update/recovery design

Prepared October 8, 2026. Aaron authorized defining this stage and rollback.
P0 and the follow-on installation-inputs inspection completed under their
separate exact approvals. See the
[latest results](installation-inputs-results-20261009.md) for observed inputs
and retained gaps. Package updates and reboot remain held until trusted inputs
and their own exact operation are reviewed and approved.

The [keyring/hook inspection](keyring-hooks-results-20261010.md) completed with
public-key identity comparisons and retained install-module review gaps. The subsequent
[trusted metadata and package-resolution definition](trusted-package-resolution.md)
now has a prepared [isolated operation](metadata-resolution-operation.md).
Its live preflight and metadata side effects require exact bundle approval;
installation remains a later stage.

## Source application decision: October 10, 2026

The governing plan now requires source-built NTPsec **and GPSD**, using adapted
clockmaker/pinup and one modernized combined timeservice. See the
[source-build audit](source-build-audit-20261010.md). APT application candidates
for ntpsec, gpsd and gpsd-clients are historical observations, not install roots.
APT remains for reviewed build prerequisites, hardware diagnostics and baseline
applications. Needrestart must report the combined service without restarting it.

The prepared metadata-resolution bundle is **superseded, never submitted**.
Its NTP/GPS roots conflict with this decision. Preserve that archive and prior
inspection evidence; do not execute or silently rebuild it under its old hash.
Prepare a replacement only after reviewing both pinned releases' build inputs,
then obtain approval for the new bundle. Existing APT trust/hook gaps remain.

The [selected release review](source-release-selection-20261010.md) now binds
signed NTPsec/GPSD release archives/tags and source-derived prerequisite roots.
The [replacement metadata operation](source-prerequisites-resolution-operation.md)
collects Python ABI/paths and resolves trusted build inputs. No executable build
profile or installation stage is ready until those target facts are observed.

## Current facts and unresolved inputs

First boot was accepted for j2-svntp1, Debian 13 Trixie, aarch64, kernel
6.18.50+rpt-rpi-v8 and DHCP 10.1.0.137. The trusted ED25519 fingerprint is
`SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys`.
Key-authenticated SSH as ama has been observed working. The original Debian 11
card is preserved; KVM, primary power and the shared antenna path were confirmed.

The [first Trixie inspection](trixie-inspection-results-20261008.md) established
NetworkManager ownership and Trixie source hints. It omitted needrestart.
Subsequent inspections confirmed needrestart is absent and the Pi fragment
suppresses kernel hints; effective replacement policy remains unaccepted.
Source hints do not prove signing-key trust, repository availability or fresh
update candidates. Fixed networking and service setup are later stages.

The [governing baseline](ntp-architecture-deployment-plan-v1.0.md#per-node-baseline-and-acceptance)
requires needrestart, non-disruptive reporting, actual kernel/service evidence
and accepted mail notification, with no unattended ntpsec restart during
acceptance. Historical Debian 11 policy is not proof of replacement-node policy.

## P0: executable read-only policy preflight

Target only j2-svntp1, using one strict-key, batch SSH connection as ama to
10.1.0.137. No primary, DNS, controller or other-node access. Reject the wrong
hostname/OS/architecture or root before running child commands. The approved
payload invokes the bundled collector with --package-policy through stdin:

```sh
cd / && /bin/bash -s
```

The exact bundled package-policy-paste.txt supplies the Python source and
invokes /usr/bin/python3 -I - --package-policy without a target staging file.
Use a 120-second SSH bound with a five-second termination allowance, strict
ED25519 checking, BatchMode=yes, UpdateHostKeys=no, connection attempts 1,
ConnectTimeout=10, no proxy/connection reuse/local command/forwarding, and
separate owner-private stdout, stderr and transport status. Preserve the
collector's PACKAGE_POLICY_EXIT_STATUS separately from SSH status. No password
collection, host-key bypass or package installation to obtain a missing tool.

P0 permits exactly the package_policy mode in inspect-trixie.py:

| Input/query | Purpose and boundary |
| --- | --- |
| Identity, kernel, boot ID | Confirm the intended non-root Trixie node and boot continuity |
| dpkg-query package status | needrestart plus the explicit APT/base/update package list; absence/unknown state remains evidence |
| apt-cache policy | Cached candidate/origin output for the fixed package list, with pkgcache/srcpkgcache output files disabled; no refresh or network request |
| dpkg --audit | Package-database diagnostic; nonempty output or error holds package mutation |
| dpkg-query -L needrestart | Installed package file locations; no program invocation |
| Selected update unit properties | apt-daily timers/services and unattended-upgrades load/active/substate, fragment path and unit-file state; no start/stop or timer edits |
| man --where | Installed needrestart/APT manual locations; no needrestart --help/version or policy evaluation |
| Policy files | Literal text, ownership/mode and hashes for the fixed main files and approved glob directories below; never source, eval or execute the contents |
| Binary metadata | lstat of /usr/sbin/needrestart and /usr/lib/needrestart/apt-pinvoke; no executable invocation |

Policy inputs are /etc/needrestart/needrestart.conf,
/etc/needrestart/conf.d/*.conf, /etc/apt/apt.conf,
/etc/apt/apt.conf.d/*, /etc/apt/preferences,
/etc/apt/preferences.d/* and /usr/lib/needrestart/apt-pinvoke. Limit the
combined set to 96 paths. Reject symlinks/nonregular files, retain permission
errors and known absence, and cap each file/stdout/stderr input at 64 KiB.
Credential-bearing lines and URI userinfo are redacted; redaction limits review
and must not be treated as proof of the omitted policy. Before/after file sets,
content hashes and ownership/mode are compared; volatile mtimes are not used.
Unchanged after-text is omitted; changed after-text remains captured.

Each of the six child queries has at most 12 seconds. The outer bound covers
the entire connection/invocation. It excludes sudo, apt-config dump, auth.conf,
SSH/relay credentials, apt update/install/upgrade/simulation, needrestart,
notification wrappers, Perl evaluation, scans, service/clock/network changes,
restart, reboot and cleanup. Ordinary OS query/audit activity may occur.

Retain package-policy-result.json and raw package-policy stdout/stderr/status
in the existing historical j1-svntp1 evidence directory, never overwriting
existing files. Record exact bundle/transport/input hashes and terminal state.
Exit 0 means collection completed without detected gaps; exit 2 retains gaps;
exit 1 or missing terminal output is incomplete. None means effective policy
is accepted. No broad rerun or tool substitution follows automatically.

## Policy review and decision before package mutation

Review whether needrestart is installed, its actual candidate/version/origin,
and the complete captured policy closure. Configuration is executable Perl;
loading it to discover its effect is outside P0. Identify main-file and snippet
ordering, restart mode, environment/CLI overrides, APT integration hooks,
custom includes/executable expressions, report/kernel filters and notification
or scheduled wrappers. If the selected policy is incomplete, unreadable,
redacted, conditional or loads uncaptured code, keep mutation held and define
the smallest further inspection. Do not infer a safe effective policy from
one list-only-looking assignment or environment variable.

The read-only common-component reference is
homelab-server-configs/Needrestart. Its current notifications documentation
targets Debian 12 and its supplied active kernel.conf targets a Pi 5 -2712
kernel. This node runs a Pi 4 -v8 kernel. Reuse the component's ownership and
reporting design after Trixie review; do not deploy that kernel file or daily
notification job unchanged. Trixie paths/options and actual kernel-image
selection remain target/version facts. No parallel common needrestart policy
or mail-delivery workflow is introduced by this stage.

Before accepting a mutation definition, require a reviewed package-database
state, trusted source/keyring inputs, known package hooks/restart behavior,
approved needrestart reporting mode, held/unresolved automatic-update activity
disposition, sufficient storage and unchanged KVM/media recovery readiness.
P0 cached candidates are not a fresh update manifest. A metadata refresh is
itself a separately defined live side effect; bind the resulting reviewed
candidate list and all policy/config inputs into the eventual mutation bundle.

## Required needrestart policy and Mailrise reporting

The next proposed collection is the
[installation-inputs preflight](installation-inputs-preflight.md). It maps the
governing plan's package requirements to collected inputs and later acceptance;
its cached metadata is not a complete trusted installation dependency closure.

Aaron requires enabled kernel checks on the rebuilding Pi. The installation
definition must make `kernelhints = 1` effective after all configuration
snippets load; batch-mode reporting alone does not satisfy this requirement.
Preserve the existing Pi fragment until its package ownership and override
order are reviewed. Select the `-v8` kernel-image filter only after capturing
the actual boot-image names and confirming how the reviewed Trixie package
matches them. The shared active Pi 5 `-2712` filter is not an input for this node.

Use explicit list-only restart mode (`restart = 'l'` and an explicit `-l` on
reporting invocations). The reviewed package's built-in session-notification
control is `sendnotify`; `sendnotify = 0` suppresses that mechanism without
removing the required external reporting route. Review the final configuration
closure and APT invocation overrides before accepting these settings.

The common component owns that external route:
[needrestart.sh and cron](../../../homelab-server-configs/Needrestart/README.md)
use `/usr/sbin/sendmail`, with
[msmtp delivering to Mailrise](../../../homelab-server-configs/Needrestart/msmtp-mailrise.md)
and Mailrise forwarding to Apprise. Keep this workflow in the installation
definition; do not replace it with built-in needrestart notifications or treat
`sendnotify = 0` as permission to omit mail acceptance. The component's examples
are proposed inputs, not observed configuration on the rebuilding Pi.

Before preparing the exact installation bundle, resolve the target's native
architecture and dependency versions, nested apt-listchanges/dpkg configuration,
Pi-fragment ownership, boot-image names and configured archive signing keys.
The locally reviewed `needrestart_3.11-1_all.deb` is not yet a trusted fresh
installation input: matching a public checksum does not complete archive
signature verification. Bind the reviewed fresh package/dependency inputs,
policy snippet and permitted hooks into the eventual installation bundle.

Notification setup also needs observed sendmail ownership, msmtp/cron state,
reviewed default-account behavior and explicit recipient/schedule inputs.
Keep `RECIPIENT` and cron `MAILTO` distinct. Enable scheduling and prove delivery
only within an authorized notification stage; no synthetic message, SMTP probe,
cron activation or Mailrise restart is authorized by this definition. The
preserved original-card rollback below remains the recovery boundary.

## Follow-on update and reboot boundaries

After P0, prepare the exact metadata/policy/package operation from its results.
If needrestart is absent, its required Trixie package and non-disruptive policy
must be established through a reviewed installation path before relying on it
during bulk updates. If present, retain or change only the reviewed owned
policy. Bind every non-secret policy file, package/version selection, executor,
permitted service effect, acceptance check and rollback command to that stage's
new hash. Do not execute a generic apt upgrade from this definition.

The eventual scope updates only this rebuilding Pi, preserving primary and
antenna power. It must name permitted APT/dpkg hooks and service restarts;
list-only needrestart behavior alone does not establish what package maintainer
scripts do. No NTP/GPSD activation, watchdog reset enablement, notification
email, fixed-network change, Wi-Fi change, controller/DNS change or primary
outage is included. Any required reboot must be explicit, use available KVM,
and record actual release/kernel, failed units, host-key continuity, DHCP/SSH
recovery and observed fan/power after boot. Do not claim full service or
hardware acceptance from a successful package update/reboot.

## Rollback and interrupted-operation handling

P0 makes no persistent configuration mutation. On identity mismatch, timeout,
policy/hash/boot drift, failed query or missing terminal record, preserve all
available output, hold package mutation and inspect the original execution
before proposing a retry. No target cleanup or compensating command is needed.

The follow-on package stage must preserve exact executed inputs and before-
state evidence. Package downgrade is not assumed reversible. On interrupted
APT/dpkg work, do not rerun upgrade or improvise dpkg repair; inspect process,
lock, database and boot state under its approved interruption path. Either
prove bounded recovery/acceptance or stop for manual intervention.

Physical rollback remains the labelled original Debian 11 card. Aaron halts
the verified rebuilding Pi at KVM with sudo /sbin/shutdown -h now when
responsive, waits for halt, removes only that Pi's power, restores the original
card and boots it. If unable to halt, last-resort removal of only this Pi's
power must be explicit in the eventual mutation authorization. Preserve the
Trixie card for diagnosis; no erase/reimage, cleanup or primary interruption.

Verify j1-svntp1, Debian 11, original root media, 10.1.0.51 and trusted old
host identity before restoring any SSH path. Run the preserved original
/usr/local/bin/ntpq semantic status/peer queries from the
[approved first-boot recovery design](first-boot-authorization.md#rejection-and-rollback),
then one bounded workstation IPv4 probe to each server using the retained
pre-rebuild-health.sh --client-ipv4. Require original PPS selection, leap 00,
stratum 1 and reviewed reach/quality plus restored direct client service.
Those recovery commands are proposed inputs for the future mutation bundle;
P0 approval does not authorize them. Failed recovery holds further changes.

## Documentation and validation

Context7 fetched official
[needrestart configuration/CLI guidance](https://github.com/liske/needrestart)
and [APT policy implementation](https://github.com/debian/apt).
The evidence must confirm this node's installed versions and configuration;
upstream documentation is not proof of target policy.

Offline tests cover wrong-host/root/OS rejection before queries, policy treated
as data, symlink rejection, credential redaction, retained policy drift,
disabled cache writes and a fixed query scope that never invokes needrestart
or apt-get. The existing test runner, pre-commit hook and CI job run these tests.
No fixture or local check proves target permissions, effective policy or
successful package updates. Bind P0's exact specification, collector, stdin
payload and retained first-boot/inspection reference to one approval hash.
