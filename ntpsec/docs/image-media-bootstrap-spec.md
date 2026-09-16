# Image, media and bootstrap specification: j1-svntp1

Draft dated `2026-09-16`; operator inputs remain pending. Implements the
[candidate/recovery plan](trixie-candidate-recovery-plan.md) under
[governing plan v1.3](ntp-architecture-deployment-plan-v1.0.md).
This is not an executable or approved write/boot bundle. No disk enumeration,
image download, media write or live infrastructure access has been performed
for this specification. Public documentation lookup is the only network work.

## Selected image

The [official OS download catalogue](https://www.raspberrypi.com/software/operating-systems/)
was checked on `2026-09-16`. Select the following release for the Pi 4B:

| Field | Selection |
| --- | --- |
| Edition | Raspberry Pi OS Lite, 64-bit, no desktop |
| Base | Debian 13, Trixie |
| Release | 2026-09-15 |
| Published kernel series | 6.18; verify actual kernel after boot |
| Filename | `2026-09-15-raspios-trixie-arm64-lite.img.xz` |
| Published download size | 516 MB; exact byte count not established |
| Published storage requirement | 2,920 MB |
| Downloaded and locally verified | No |

Exact [official image URL](https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-09-15/2026-09-15-raspios-trixie-arm64-lite.img.xz).
Published SHA-256 for the compressed download:

```text
cdf4f3bfac35ae947b46e4e767f935453810549779ac3290e05a6754aee627e5
```

The catalogue supplies the release and hash. The browser fetch of the binary
and release notes returned HTTP 403; no image bytes or release notes were
verified. This does not establish that Imager or a future download will fail.
Before writing, obtain the exact official artifact, check its local SHA-256
against this value and record the installed Imager version. A mismatched hash,
missing artifact, different release or wrong edition blocks writing. Do not
silently substitute a moving latest image. Reconcile a newer selection in this
specification and the later approval bundle first.

Imager may write this exact release through its catalogue if metadata matches,
or use the verified custom image with supported customization. Validate that
the actual installed Imager supports the chosen route before authorization.
A published hash is an integrity reference, not evidence of a verified write
or of hardware compatibility. Do not compare a customized/expanded card's
whole-device hash with the compressed download hash.

## Operator inputs required

| Input | Known or unresolved |
| --- | --- |
| Operator | Aaron |
| Writer workstation and OS | Windows, operator-confirmed; exact workstation identifier/version pending |
| USB reader attachment | USB reader connected directly to Windows; no WSL passthrough |
| Spare | SanDisk Max Endurance microSDXC 128 GB, new in packaging; disk identity and write authorization still pending |
| Original | Working Debian 11 card remains untouched for rollback; protected baseline contains media identifiers |
| Imager version | 2.0.11.1 on Windows, reported by Aaron; exact installed UI capabilities not independently verified |
| Bootstrap administrator | ama, operator-confirmed |
| SSH public key | Install after first boot; public-key path/reference and fingerprint pending |
| First access | Password-authenticated SSH over Ethernet eth0 using DHCP for first boot; static assignments after first boot; KVM retained |
| Console login/sudo | Aaron sets the account/SSH password privately in Imager; verify console login and sudo behavior at first boot |
| Wi-Fi | Operator requests disabled in Imager; verify resulting disabled state on target |
| Maintenance window | Anytime, confirmed by Aaron; record actual execution timestamps |
| Maximum outage and discovery cutoff | No fixed limit: Aaron allows as long as needed for j1-svntp1; failure-based recovery applies |
| Keyboard/time zone customization | Pending operator selection; do not infer from workstation locale |

Missing entries are blocking inputs for a concrete execution request, not
permission to choose credentials, erase media or start a maintenance window.

## Media identity and future write boundary

Record a short operator label for the spare, its visible brand/capacity, the
reader connection, OS disk identifier, model, exact byte capacity and serial
or unique ID if exposed. A reader serial may identify the reader rather than
the card; capacity or a drive letter alone is insufficient.

In a separately authorized preparation step, correlate insertion/removal of
only the spare with the writer's disk list and with Imager's selected target.
Do not detach the running node's old card to identify the spare. Resolve any
ambiguity, mounted user data or unexpected disk layout before proposing a
write. Keep the old card and workstation/system disks excluded by identity,
not merely by their current disk numbers. Recheck the identity immediately
before the destructive write; stop if it changed.

A later media-only authorization must name the exact target, erase consent,
image hash, Imager version/customization settings and allowed write/verification
operations. It does not authorize booting a node. Record write and verification
results separately; do not skip verification. On failure retain the result,
leave the old card untouched and do not retry or select another disk implicitly.
Safely eject and label successful spare media for j1-svntp1. Do not insert or
boot it before the separate maintenance gate.

## Bootstrap proposal and identity handling

The proposed hostname is the governing node identity, j1-svntp1. Never boot a
second device with that identity while the original is running. Generate fresh
machine identity and SSH host keys on the replacement; do not clone the Debian
11 private host keys merely to suppress a known-hosts warning.

Aaron selected password-authenticated Ethernet SSH for first boot, using
administrator **ama** and an account password he sets privately in Raspberry
Pi Imager. Add his SSH public key after first boot. This replaces the earlier
key-only-from-imaging proposal. No password value or private key belongs in
chat, Git, logs or this specification. The
[official SSH documentation](https://www.raspberrypi.com/documentation/computers/remote-access.html#ssh)
is a reference; verify the actual installed Imager settings before writing.

In the later authorized bootstrap operation, verify the new host identity,
log in as ama over Ethernet, and install only the approved public key with
correct ownership and permissions. Keep the initial session and KVM available
while testing a separate new key-authenticated session and required sudo
access. Disable SSH password authentication only after those tests pass and
that change is included in the approved bootstrap scope; validate the effective
SSH settings and test another new session before closing the recovery session.
On failure retain the working access path and diagnose within the approved
scope. Do not assume the old sudo -n behavior carries over.

Disable Wi-Fi in Imager as requested and configure no wireless credentials.
Record the actual version's available setting and verify the resulting Wi-Fi
state during target discovery: omission of an SSID alone does not prove the
radio is disabled. If Imager cannot enforce the disabled state, include the
required image/target setting in the later reviewed bootstrap scope rather
than silently claiming completion. Ethernet eth0 is the requested interface;
confirm its actual name and manager on the target before rendering profiles.

Aaron corrected the bootstrap choice to **Ethernet DHCP for first boot**,
with static assignments applied after first boot. No static-IP customization
in Imager is required. The DHCP address is not predetermined and must not be
assumed to equal the old static address. During the later authorized first boot,
Aaron will confirm the assigned IPv4 address in UniFi Network first, matching
the current client record to this node's captured Ethernet MAC. If the address
is unavailable or ambiguous, he will use the KVM to inspect it locally. This
is an operator lookup, not authorization for an agent controller query.
Address discovery does not replace the SSH host-key verification below.
If no usable lease is obtained, use the failure-based stop conditions and recovery
path rather than inventing an address or changing the controller.

After establishing access, observe the installed network manager, interface,
active profile and resolver ownership. In the later approved configuration
scope, apply the governing plan's static IPv4 and permanent ULA, gateway and
DNS requirements while preserving RA/global IPv6 behavior. Define console
recovery and reconnection to the new address before changing the profile;
then verify fresh SSH access, both address families, DNS ownership and reboot
persistence. DHCP bootstrap success does not establish final network acceptance.
The original node must be down before booting its replacement identity; no
DHCP reservation or controller change is implied by this choice.

At the console, verify node identity and record the new host-key fingerprint
before trusting SSH. Keep the previous host-key evidence for old-card recovery;
use an operation-specific trusted entry or a deliberate verified replacement,
never disable host-key checking or delete unrelated known-hosts entries. On
rollback, verify the old fingerprint again. Do not enable Wi-Fi or Raspberry Pi
Connect as an unapproved alternative access path.

## Maintenance timing and first-boot stop conditions

Aaron permits j1-svntp1 maintenance **anytime, for as long as needed**. There
is no fixed outage deadline, discovery cutoff or separate recovery allowance
to obtain. This timing decision does not authorize a write, first boot or live
action, and does not extend to an outage of the primary j1-svntp.

Use failure-based recovery: stop and assess if boot or access cannot be
recovered within the approved procedure, hardware/power health is unsafe,
the surviving primary or antenna-power path is impaired, or required acceptance
fails. Aaron may elect old-card recovery at any point. Preserve available
diagnostics, keep the primary serving and follow the candidate plan's recovery
sequence. Do not continue uncontrolled retries or improvise changes outside
the approved scope just because no time limit applies.

The first-boot bundle must still define bounded individual commands, checks,
permitted package/network/service changes and rejection behavior. Acceptance
thresholds and an observation interval are separate from the outage allowance
and remain to be defined. A failed validation is not converted to success by
waiting indefinitely.

## Baseline gaps by gate

| Gate | Evidence or decisions still needed |
| --- | --- |
| Before spare write | Exact Windows spare identity and write consent, artifact hash verification, Imager version and finalized bootstrap settings |
| Before first-node outage | Phase 1 gap disposition, readable verified backup and old-card identification procedure, usable console, primary/client health, bootstrap network route, confirmed unrestricted timing and failure-based recovery |
| During authorized target discovery | Actual Trixie network/unit/config paths, package provenance, hardware overlays/devices and permissions, sudo/host identity; no guessed Debian 11 carryover |
| Before target acceptance | Full dual-stack clients and resolver persistence, GPS/PPS/RTC and PoE/fan health, leap behavior, app/mail/Munin tests, recovery verification, numeric time-quality limits and observation interval |
| Before primary outage | Its own baseline and media/recovery readiness, verified shared antenna-power continuity and family-specific DNAT transition |

The missing legacy firewall tools, source-build provenance and historical
leap-download details remain in the Phase 1 checklist. Their disposition must
be explicit before declaring baseline acceptance; this draft does not waive
those requirements or authorize another collector run.

## Evidence and next gate

Reuse the existing protected host evidence directory. The later write proposal
should retain one bounded media-preparation record containing image metadata,
verified digest, writer/version, non-secret customization, media identity,
write/verification outcome and timestamps. Put sensitive Imager logs only in
protected files if needed; never commit customized images, passwords or keys.
Specify filenames and overwrite rejection in the final bundle; do not create
per-action directories or duplicate baseline extraction trees.

Next: incorporate the operator's pending answers, then prepare the concrete
media-only operation definition with exact target and artifact identities.
No write authorization can be requested for an ambiguous disk. First boot and
live preflight remain separate scopes. This specification records a selected
image, not a downloaded/verified artifact or accepted Trixie node.
