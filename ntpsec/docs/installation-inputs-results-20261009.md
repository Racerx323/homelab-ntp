# Trixie installation-inputs inspection results

Observed October 9, 2026, on the rebuilding `j2-svntp1`. Aaron authorized bundle
SHA-256 `9d2e34dc0221a4d456beb1aafa8d0056d1d27666c1622cf7cd474495dd60e4cc`.
One pinned-key, non-root SSH invocation submitted the exact bundled stdin
payload. No retry, sudo or remote staging occurred. The
[operation specification](installation-inputs-preflight.md) remains the scope
reference; this document records its terminal outcome.

## Outcome and continuity

SSH transport and collector both returned 2, indicating retained collection
gaps. The complete terminal marker and JSON report were preserved; SSH stderr
was empty. This is a completed inspection with gaps, not installation acceptance.
Boot ID was unchanged, sampled policy and metadata showed no drift, and the
dpkg audit was clean. Identity remained Debian 13 Trixie/aarch64 with kernel
`6.18.50+rpt-rpi-v8`. dpkg native architecture is arm64; armhf is configured as
a foreign architecture. These observations do not authorize removing armhf.

Raw stdout/stderr, registration/transport state, parsed result, exact archive,
payload and pinned known-host entry remain in the existing owner-private
evidence directory. Original artifacts were not overwritten. No package
refresh/install, service/timer change, restart, reboot, SMTP probe or mail ran.

## Package and policy observations

needrestart, msmtp and msmtp-mta are absent. The default sendmail path, msmtprc,
aliases and the common reporting cron job are absent. cron 3.0pl1-197 is
installed, enabled and active. An absent msmtp systemd service is not itself a
failure: this workflow uses a sendmail-compatible command, not an msmtp daemon.

The reviewed needrestart package's Perl, dpkg, gettext-base, procps and xz-utils
dependencies are installed. Its libintl-perl, libproc-processtable-perl,
libsort-naturally-perl, libterm-readkey-perl and libmodule-find-perl dependencies
are absent. libpam-systemd and systemd are installed; this does not establish
the solver's final selection of recommended alternatives.

The broader baseline packages ntpsec, gpsd, gpsd-clients, pps-tools, i2c-tools,
watchdog, webmin and munin-node are absent. Legacy Raspberry Pi kernel package
names and optional support-package queries also produced absence records;
those query names are not an installation manifest. Current linux-image-rpi-v8,
raspi-firmware, raspi-utils and rpi-eeprom packages are installed.

Cached candidates include needrestart 3.11-1, msmtp/msmtp-mta 1.8.28-3, ntpsec
1.2.3+dfsg1-8, gpsd 3.25-5+deb13u2, watchdog 5.16-1.1+rpt1 and munin-node
2.0.76-5. No Webmin candidate record was returned. Do not infer Webmin provenance
or availability from an apt-cache success status. None of these cached values
is a fresh trusted installation input or a complete dependency resolution.

APT update/upgrade timers were enabled and waiting; their services were
inactive at the query. The unattended-upgrades service was not found. The
captured hooks invoke apt-listchanges and dpkg-preconfigure. listchanges uses
the pager frontend, news selection, email_address=root and a save_seen path
under /var/lib/apt; confirm is false. Installation must review actual hook
behavior and specify noninteractive/mail effects before execution approval.

## Kernel and signing-key gaps

`raspberrypi-sys-mods` owns `/etc/needrestart/conf.d/rpi-kernel.conf`, which
suppresses kernel hints. Both `/boot/vmlinuz-6.18.50+rpt-rpi-v8` and the parallel
`-2712` image exist, as do firmware kernel8.img and kernel_2712.img. This supports
reviewing a v8-specific filter while requiring an effective kernelhints = 1
override; the shared active Pi 5 filter remains unsuitable for this node.
Image content, actual needrestart image-selection behavior and effective
configuration are not accepted by this metadata-only collection.

debian-archive-keyring 2025.1 and raspberrypi-archive-keyring 2025.1+rpt1 are
installed. The observed Signed-By paths are:

- `/usr/share/keyrings/debian-archive-keyring.pgp`
- `/usr/share/keyrings/raspberrypi-archive-keyring.pgp`

The executed metadata patterns covered .gpg/.asc but omitted .pgp. Thirteen
.gpg aliases were rejected as symlinks and pointed to .pgp filenames. The
source-referenced .pgp files were therefore not captured or hashed, and no
public-key fingerprint or signature-chain trust was established. This is a
collector coverage gap, not evidence of a broken repository keyring. Future
collection now includes .pgp without following the aliases; the executed bundle
remains unchanged and was not rerun.

## Next boundary

Define a narrowly scoped inspection of the two observed .pgp keyrings and their
package provenance, plus the authoritative hook behavior still needed for
installation. Then define fresh signed metadata acquisition and reviewed exact
APT dependency resolution. Each further live stage needs its own exact bundle
approval; this inspection does not authorize those commands.

Keep explicitly enabled kernel checks, list-only service restart reporting and
the common msmtp/Mailrise notification route in the eventual installation
definition. Notification configuration, recipients, scheduling and delivery
remain unaccepted. Preserve the old Debian 11 card, primary-node power and
shared antenna wiring. The [package-stage definition](trixie-package-stage.md)
owns the proposed installation/recovery boundaries.
