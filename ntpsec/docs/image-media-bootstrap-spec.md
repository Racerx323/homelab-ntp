# Image, media and bootstrap specification: j2-svntp1

Updated `2026-10-08`: Imager write and 100% verification complete, operator-confirmed; first boot pending. Implements the
[candidate/recovery plan](trixie-candidate-recovery-plan.md) under
[governing plan v1.4](ntp-architecture-deployment-plan-v1.0.md).
Media-only write/verification of the exact October 6 artifact to the confirmed
spare was approved on 2026-10-08 and Aaron supplied Imager completion evidence.
Read-only Windows disk identification and official image verification were
performed; no NTP-node access or first boot is included.

## Selected image

Aaron confirms selecting Raspberry Pi OS Lite (64-bit) from Imager's catalogue.
The [official Imager catalogue](https://downloads.raspberrypi.com/os_list_imagingutility_v4.json)
checked on `2026-10-08` points to **2026-10-06**, Debian Trixie arm64 Lite,
compatible with Pi 4. This replaces the September 15 candidate; that historical
artifact remains retained, but its hash does not verify this new selection.

[Exact October image](https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2026-10-06/2026-10-06-raspios-trixie-arm64-lite.img.xz):
`2026-10-06-raspios-trixie-arm64-lite.img.xz`.

| Verification | Expected value |
| --- | --- |
| Compressed size | 550466056 bytes |
| Compressed SHA-256, official sidecar | `483db18a48da399b5b7022ffae9a07bc6d99daab30e593aedac09b69ff422843` |
| Expanded size, catalogue | 3078619136 bytes |
| Expanded SHA-256, catalogue | `b8a393dc1c3701450b5fffbfe74368a98fb6eab7415ce456cc0cead886ea8780` |

Downloaded into the existing protected evidence directory; streaming checks
verified both representations without extracting another image file. Retain
`image-verification-20261006.json` alongside the compressed artifact. Aaron
subsequently supplied a Write complete screenshot. Installed kernel and package
versions remain target inputs.

The OS-selection screenshot confirms release 2026-10-06, closing the catalogue
session identity check. The subsequent Imager 2.0.12 completion screenshot
shows Pi 4, Lite 64-bit, Generic STORAGE DEVICE, and applied hostname,
localisation, user-account and SSH customizations. It reports automatic safe
ejection. Aaron separately confirmed that verification completed to 100% after the
write without being skipped. This closes media-write verification; it is
operator evidence, not an independently performed agent readback.
It does not establish target Wi-Fi state or reveal individual account settings.
Use custom was unsuitable for applying customizations; the catalogue route
was retained. No additional readback or re-imaging is requested by this record.

## Operator inputs required

| Input | Known or unresolved |
| --- | --- |
| Operator | Aaron |
| Writer workstation and OS | Windows, operator-confirmed; exact workstation identifier/version pending |
| USB reader attachment | USB reader connected directly to Windows; no WSL passthrough |
| Spare | SanDisk Max Endurance microSDXC 128 GB, new in packaging; Imager reports Generic Storage Device USB Device, 127.9 GB; Windows G: maps to partition 1 on candidate disk 5, 127865454592 bytes, USB reader serial 000000009451; Aaron visually confirmed this new card in the selected reader; physical identification complete; October 6 media-only write/verification approved 2026-10-08 |
| Original | Working Debian 11 card remains untouched for rollback; protected baseline contains media identifiers |
| Imager version | 2.0.12, observed in the 2026-10-08 review-screen screenshot; supersedes earlier 2.0.11.1 report |
| Bootstrap administrator | ama; operator reports password set and SSH password authentication enabled in Imager |
| Hostname entered in Imager | j2-svntp1; intentional rebuild rename approved 2026-10-08 |
| SSH public key | Install after first boot; public-key path/reference and fingerprint pending |
| First access | Password-authenticated SSH over Ethernet eth0 using DHCP for first boot; static assignments after first boot; KVM retained |
| Console login/sudo | Aaron sets the account/SSH password privately in Imager; verify console login and sudo behavior at first boot |
| Wi-Fi | Operator requests disabled in Imager; verify resulting disabled state on target |
| Maintenance window | Anytime, confirmed by Aaron; record actual execution timestamps |
| Maximum outage and discovery cutoff | No fixed limit: Aaron allows as long as needed for j1-svntp1; failure-based recovery applies |
| Keyboard/time zone customization | Operator reports US/Washington DC localisation, America/Chicago time zone, US keyboard |

Missing entries are blocking inputs for a concrete execution request, not
permission to choose credentials, erase media or start a maintenance window.

## Media identity and future write boundary

Read-only Windows metadata maps G: to partition 1 of disk 5, Generic
STORAGE DEVICE, 127865454592 bytes, USB reader serial 000000009451; neither
boot nor system disk. Aaron visually confirmed that the new SanDisk spare is
in that reader and Imager still selects that device. This combined evidence
satisfies physical identification without disconnecting the reader or losing
the pending customization session. Do not require removal/reinsertion.

The supplied review screenshot shows Raspberry Pi 4, Raspberry Pi OS Lite
(64-bit), the Generic STORAGE DEVICE target, and configured hostname,
localisation, user and SSH. It does not expose the individual customization
values or image release/hash. That initial review was followed by the October 6 release screenshot and
Write complete screenshot described above. Media approval and the write are
complete; do not repeat the write.

Preserve the original card. Immediately before writing, confirm the same
selected spare; stop if the target changes. A future reconnect may change disk
numbers or drive letters and requires refreshed identity checks.

A later media-only authorization must name the exact target, erase consent,
image hash, Imager version/customization settings and allowed write/verification
operations. It does not authorize booting a node. Record write and verification
results separately; do not skip verification. On failure retain the result,
leave the old card untouched and do not retry or select another disk implicitly.
Safely eject and label successful spare media for j2-svntp1. Do not insert or
boot it before the separate maintenance gate.

## Bootstrap proposal and identity handling

The approved target hostname is **j2-svntp1**, replacing j1-svntp1 on the
same physical node during the rebuild. Preserve historical evidence and the
old-card hostname as j1-svntp1. The existing IP assignments and service FQDN
remain unchanged; follow plan v1.4's record-reconciliation gates. Never boot a
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

Next: complete the current-service preflight required by governing Phase 3.1,
then finalize the first-boot/recovery operation for separate authorization. Safely
store and label the ejected spare j2-svntp1; retain the original Debian 11 card
untouched. No node boot, shutdown, card swap or service change is authorized
by the media-only approval. Baseline and Trixie acceptance remain open.

## Proposed first-boot and recovery scope

Media gate is complete. The proposed operation concerns only the physical
node currently named j1-svntp1 (10.1.0.51), to boot as j2-svntp1. It is not
approved for execution yet. Aaron performs console and physical actions.

1. Before shutdown, obtain current evidence that j1-svntp serves clients and
   the active IPv4 DNAT target is reachable. Record client impact, including
   any clients pinned solely to the rebuilding node, as required by Phase 3.1.
   Historical September snapshots are insufficient. Define a separate bounded
   read-only collection if existing operator evidence cannot establish this;
   no agent access to primary, controller or DNS is implied here.
2. Confirm usable KVM, readable protected baseline archive, identified original
   card and unchanged antenna-power path. Stop on ambiguity or an unhealthy
   surviving service. Classify remaining Phase 1 gaps before allowing outage.
3. Under the future approved operation, gracefully shut down only the current
   j1-svntp1. Aaron safely removes and labels its original Debian 11 card,
   inserts the verified spare and powers on that same node. Preserve the
   primary, antenna and splitter wiring throughout.
4. Aaron identifies its DHCP address in UniFi, using KVM if needed. Verify
   hostname j2-svntp1, Trixie arm64 identity, new SSH host fingerprint, boot
   media, fan/power health and access as ama. The first-boot customization
   itself writes the new card; do not describe this operation as read-only.
5. Stop at bootstrap inspection. Define exact inspection commands and retained
   output before requesting execution. No package installation, static-address
   change, public-key installation, SSH policy change or NTP configuration is
   included in this proposed first-boot scope.
6. On boot/access/power failure or Aaron's decision to stop, preserve diagnostics
   and recover using the original card under the candidate plan's recovery
   sequence. Verify restored Debian 11 identity and NTP client service. A
   failed recovery is not success; retain evidence and obtain scoped diagnosis.

Before authorization, bind the finalized operation and its exact non-secret
inputs to a hash; document preflight evidence, commands, acceptance and
rollback. No renewed imaging approval is needed and no re-image is planned.
