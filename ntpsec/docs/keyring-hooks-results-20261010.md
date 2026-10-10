# Trixie keyring and hook inspection results

Observed October 10, 2026, on the rebuilding `j2-svntp1`. Aaron approved bundle
SHA-256 `d4a4850654845c7db25905f6b51d72abe5eb80dac2c527cd021c7bf5bc5e5f99`.
One registered, non-root, pinned-key SSH invocation ran its exact stdin payload.
The [executed specification](keyring-hooks-preflight.md) remains preserved in
the private archive. No retry, sudo or target staging occurred.

## Terminal outcome

SSH transport and collector both returned 2. Complete JSON and the terminal
marker were preserved; SSH stderr was empty. Boot ID remained unchanged, inputs
and queried package versions/file lists showed no drift, dpkg audit was clean,
and dpkg package-file verification produced no findings. No child query failed,
timed out or truncated, and no input-read error was reported.

The collection retained gaps: six Debconf modules contain eleven lines removed
by credential-word redaction, and the actual apt-listchanges implementation
modules were outside the executed path boundary. Configuration absence was
retained for apt.conf, preferences and needrestart's not-yet-installed main
configuration/hook. Neither local package checksums nor completed collection
accepts archive signature trust or effective install-hook behavior.

Full stdout/stderr, registration/transport record, parsed result, exact archive,
payload, captured keys and local review outputs remain owner-private under the
existing evidence directory. No target refresh, simulation, package download/
installation, timer/service change, reboot, SMTP probe or mail occurred.

## Public keys and provenance

Both source-referenced .pgp keyrings were captured as bounded public bytes with
hash, ownership and mode. Package-file verification was clean for
debian-archive-keyring 2025.1, raspberrypi-archive-keyring 2025.1+rpt1,
apt-listchanges 4.8 and debconf 1.5.91. APT is 3.0.3; gpgv is
2.4.7-21+deb13u1+b5, sqv is 1.3.0-3+b2 and raspberrypi-sys-mods is 1:20260914.
Installed verifier packages alone do not prove which path APT actually uses.

Local GPG public-key inspection used a protected temporary workstation home
and disabled automatic retrieval. No key was imported on the Pi. All nine
captured Debian primary fingerprints matched the Debian FTP master publisher
key listing fetched locally over certificate-validated HTTPS. The captured
Raspberry Pi primary fingerprint, CF8A1AF502A2AA2D763BAE7E82B129927FA3303E,
matched the publisher's archive public key fetched over validated HTTPS.

Publisher responses, transport URLs/checksums, local GPG output and comparisons
are retained in private keyring-hooks-publisher-fetch.json,
keyring-hooks-key-review.json and keyring-hooks-publisher-comparison.json.
These are identity comparisons, not validation of a fresh Release/InRelease,
its expiry, package indexes or an installation archive. Signature-chain
acceptance remains false pending the separately authorized metadata stage.

## Hook observations and remaining closure

The captured APT configuration has two dpkg pre-install hooks: apt-listchanges
and dpkg-preconfigure. No update pre/post-invoke hook appeared in the captured
configuration. listchanges uses a pager, news selection, email_address=root
and a persistent save_seen path; these effects remain relevant to installation.
The captured wrapper imports apt_listchanges.apt_listchanges.main.

The package-file list places the actual Python implementation under
`/usr/lib/python3/dist-packages/apt_listchanges/`. The executed collector allowed
Python modules only under `/usr/share/apt-listchanges/`, so it did not capture
the main implementation, config/frontends or other listed Python modules.
Future capture now includes the observed path and has an offline boundary
regression. The executed bundle and paste were not changed or rerun.

The eleven redacted lines are in Debconf DbDriver, Directory, LDAP, Dialog,
Readline and Teletype modules. Their presence is a review limitation, not an
observation that credentials were installed there. The reporting policy and
actual install-hook closure cannot be accepted from elided source.

## Next boundary

Prepare the exact [trusted metadata/resolution bundle](trusted-package-resolution.md)
with the remaining bounded module read in its preflight, current source/key/
policy/package continuity checks, installed APT/verifier validation, privilege
and automatic-APT disposition, and explicit metadata side effects/recovery.
Do not rerun either completed inspection to replace its gaps.

Separate metadata-refresh safety from install-hook acceptance. The next stage
must execute neither dpkg pre-install hook nor install packages. Missing install
module review must continue to block installation and mail effects; any input
needed for metadata safety must fail the next stage before refresh. Fresh
signed metadata and exact complete dependency resolution are still unperformed
and require their own approved hash-bound operation.

Preserve explicitly enabled kernel checks, list-only service reporting and the
common msmtp/Mailrise notification route. Webmin provenance and hardware/service
acceptance remain unresolved. Original Debian 11 media, primary-node power and
shared antenna wiring remain preserved.
