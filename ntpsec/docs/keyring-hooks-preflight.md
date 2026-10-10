# Trixie keyring and hook inspection

Prepared October 10, 2026. Aaron authorized defining this inspection and the
following trusted package-resolution stage. Execution requires approval of
this inspection's exact private bundle SHA-256.

Target only non-root `ama@10.1.0.137`, hostname `j2-svntp1`, Debian 13 Trixie,
aarch64. Require the retained console-verified ED25519 fingerprint
`SHA256:yXiID8RObBoIejVpvr2KesaqIlocbSORyemD5dKrEys`. No primary, DNS,
controller or Mailrise-host access is included.

## Inputs and query boundary

The bundled collector runs `--keyring-hooks` and rejects the wrong host, OS,
architecture or root identity before child queries. It addresses the gaps in
the [completed input inspection](installation-inputs-results-20261009.md);
neither prior inspection is rerun.

Capture these source-referenced public keyrings as base64 bytes with hash,
owner/group/mode and a 64 KiB limit per file:

- `/usr/share/keyrings/debian-archive-keyring.pgp`
- `/usr/share/keyrings/raspberrypi-archive-keyring.pgp`

Reject symlinks/nonregular files; do not follow the .gpg aliases, import keys,
invoke a signature verifier or infer authenticity from a checksum. Retain
absence, permission/size failures and before/after drift. Key fingerprints and
independent trust must be reviewed locally after the approved capture.

Read the actual `/usr/bin/apt-listchanges` and `/usr/sbin/dpkg-preconfigure`
programs as text, never invoking them. Capture package-listed Python modules
only under `/usr/share/apt-listchanges/` and Perl modules only under
`/usr/share/perl5/Debconf/`. Reject parent traversal; do not follow imports or
includes automatically. Capture the current APT/needrestart policy closure,
source files, listchanges main/parts and dpkg configuration. Do not capture
relay credentials, home directories, private keys or arbitrary package files.

Read six fixed installed manuals: apt-listchanges, dpkg-preconfigure, apt-get,
apt-secure, apt.conf and sources.list. Compressed manuals have a 64 KiB stored
input limit and 256 KiB expanded limit. All other files retain the 64 KiB bound;
the combined path set is limited to 128. Redact credential-bearing text; mark
redaction as a coverage gap. Missing manuals and unresolved imports remain
review inputs, never proof that the corresponding behavior is safe.

Run exactly nine bounded child queries:

| Query | Purpose |
| --- | --- |
| dpkg-query package versions, before and after | apt, apt-listchanges, debconf, both archive keyring packages, raspberrypi-sys-mods, gpgv and sqv; preserve missing packages |
| dpkg-query hook-package file lists, before and after | Discover only the bounded modules owned by apt-listchanges/debconf |
| dpkg-query ownership | Both .pgp files, both hook programs and the Pi fragment |
| dpkg --verify | Local package-file checksum evidence for both keyrings and hook packages; no independent archive trust assertion |
| dpkg --audit | Package-database health |
| apt-get --version | Installed APT capabilities/version; no package-manager operation |
| systemctl show | APT timers/services and unattended-upgrades state only |

Compare input hashes/metadata, module file sets, queried package versions and
boot ID before/after. Each child has a 12-second timeout and 64 KiB stdout/stderr
caps. Preserve nonzero status and truncation. Nine queries do not imply nine
acceptance decisions: programs, modules, manuals, keys and overrides require
review together. Effective hook policy and signature trust remain false in the
collector report, even when collection completes without detected gaps.

## Transport and terminal handling

Use one strict-key, batch SSH invocation with the pinned known-host entry,
240-second transport bound and five-second termination allowance. Disable
proxies, connection reuse, forwarding, local commands and host-key updates.
Invoke the exact bundled stdin payload through `cd / && /bin/bash -s`.
The private bundle manifest contains the exact workstation argv and every
non-secret execution input; its external approval manifest identifies paths.

Immediately before an authorized submission, verify the archive/member hashes,
payload and pinned key. Register before submission. Retain complete stdout,
stderr, transport status, JSON and the distinct KEYRING_HOOKS_EXIT_STATUS marker
in the existing owner-private evidence directory without overwriting files.
Exit 0 means completed collection, 2 means retained gaps, and 1/missing terminal
data means incomplete collection. Do not resubmit to replace an error or gap.

## Mutation, recovery and follow-on review

No sudo, metadata refresh, download, simulation, package install, timer/service
change, reboot, hook execution, SMTP probe or mail is authorized. Normal
read-only command activity may occur. No target staging or cleanup is needed.
On identity mismatch, timeout, drift or incomplete evidence, preserve the
original execution and hold all later changes. Old-card recovery remains the
future installation boundary, with primary/antenna power untouched.

Review the captured public keys, package provenance and complete relevant hook
behavior before rendering the
[trusted package-resolution stage](trusted-package-resolution.md). In
particular, resolve update hooks, listchanges pager/mail/save_seen behavior,
debconf preconfiguration, privilege availability and the installed APT
signature-verification path. This approval cannot authorize those later actions.
