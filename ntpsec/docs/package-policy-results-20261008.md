# Package-policy preflight results: October 8, 2026

Executed approved P0 once as non-root ama on j2-svntp1 at 10.1.0.137.
Bundle SHA-256:
`9df701beefe20f5e2e5eaee6a128738c2c0339db3369a1e4ab25a7aa48c13772`.
Verified the archive, all five manifest-covered members, exact stdin paste,
bound prior evidence and the console-matching ED25519 host key before one
strict, key-authenticated SSH execution. No retry or target staging occurred.

SSH status 0; collector status 2; SSH stderr empty. Retained all 10,111 stdout
bytes, stderr, terminal transport status and parsed report as owner-private
package-policy.* and package-policy-result.json in the existing historical
j1-svntp1 evidence directory. The completed artifact and paste remain unchanged.

## Needrestart is not installed as a package

dpkg-query reported no package matching needrestart and its package-file query
reported that it is not installed. apt-cache policy reported Installed: (none)
and cached Candidate: 3.11-1 from Debian trixie/main. /usr/sbin/needrestart,
/usr/lib/needrestart/apt-pinvoke and /etc/needrestart/needrestart.conf were
absent. No installed needrestart manual was found.

This resolves the omission in the first inspection: needrestart is required
but not installed as a Debian package on the replacement image. It does not
claim exhaustive absence of similarly named custom programs elsewhere. The
candidate comes from existing cache, not a fresh metadata refresh or accepted
update manifest. No needrestart executable or configuration was evaluated.

An existing root-owned 0644 fragment, /etc/needrestart/conf.d/rpi-kernel.conf,
contains `$nrconf{kernelhints} = 0;` with comments about avoiding Raspberry Pi
kernel-version/flavour false positives. Its package owner was not queried.
Main configuration and runtime are absent, so there is no accepted effective
restart/reporting policy. Preserve and review this fragment before reconciling
the governing requirement for actual kernel reporting; do not blindly copy the
common component's Pi 5 -2712 filter onto this Pi 4 -v8 node.

## Package database, hooks and periodic updates

dpkg --audit returned 0 with empty stdout/stderr. No sampled policy-file set,
content/owner/mode or boot-ID drift was detected. This is a bounded snapshot,
not a whole-system integrity or concurrency guarantee.

Cached installed/candidate versions for the other queried base packages matched:
APT 3.0.3, libc6 2.41-12+rpt1+deb13u4, systemd 257.13-1~deb13u1,
OpenSSH server 1:10.0p1-7+deb13u4, linux-image-rpi-v8
1:6.18.50-1+rpt1 and raspi-firmware 1:1.20260915-1. Do not interpret those
cache matches as proof that the node is fully updated or has no security updates.

apt-daily.timer and apt-daily-upgrade.timer are loaded, enabled and active/
waiting. Their services were inactive/dead at the snapshot. The
unattended-upgrades package query found no match and its service is not-found.
No timer or service was stopped, disabled or changed; absence of that package
does not establish every form of automatic APT activity.

The three captured APT snippets are root-owned 0644. They define autoremove
policy and two package pre-install hooks: apt-listchanges --apt and
dpkg-preconfigure --apt. The listchanges hook references listchanges.conf and
listchanges.conf.d, which were outside P0's selected inputs and remain
unreviewed. P0 invoked no hook or mail delivery. Their eventual noninteractive
and notification behavior must be included in the next package-stage review.
No /etc/apt/apt.conf or /etc/apt/preferences file was present in the selected
projection. This is not a complete effective APT configuration dump.

## Collection gaps and next gate

Keep collector status 2. Its gaps are the absent required package, failed
package-file query and unavailable installed needrestart manual. Those are
useful target facts, not a reason to repeat this collection or install a tool
outside an approved stage. The package database audit, cache query and sampled
policy/boot continuity checks completed without error or truncation.

The next definition must account for the required needrestart installation,
reviewed non-disruptive restart policy, kernel reporting/fragment ownership,
APT hook and timer behavior, source/keyring trust and fresh package candidates.
Review any uncaptured hook inputs through a narrow approved scope. Metadata
refresh, package installation, policy writes and reboot are live side effects
that need their own exact specification, inputs and approval. Use the
[package-stage recovery design](trixie-package-stage.md#rollback-and-interrupted-operation-handling)
and preserved old card; do not assume package downgrades are rollback.

P0 performed no APT refresh, download, install, update, needrestart invocation,
Perl evaluation, timer/service/clock/network change, notification or reboot.
First-boot acceptance remains separate from full platform/service acceptance.
