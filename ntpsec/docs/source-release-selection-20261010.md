# NTPsec/GPSD source release selection

Prepared October 10, 2026 under Aaron's source-selection/preparation approval.
Public downloads, signature verification and source inspection occurred on the
workstation only. No Pi contact, build, installation or notification occurred.

## Selected releases and authentication

| Application | Publisher release | Signed tag | Pinned commit |
| --- | --- | --- | --- |
| NTPsec | 1.2.5 | NTPsec_1_2_5 | 42b5703303c8c7e6513f3a119cfab670924dd7be |
| GPSD | 3.27.5 | release-3.27.5 | 1d622f5b2c7bf79fc117185be10048e7d4e73c66 |

These were the highest numbered releases in the reviewed publisher indexes on
October 10; selection remains pinned even if a later release appears.

- NTPsec archive SHA-256:
  `6fb191cddaf607e7754b1f6915a1a61dc4018b3e4eef3d2ffacec961c9682949`.
- GPSD archive SHA-256:
  `409873f5048462ef1ac413a51ab35caa8b50b31be62b3347bee1cc2994e7c649`.
- NTPsec release/tag signer and primary fingerprint:
  `E57235D22764129FA4F2F4D17F52608ED0E49D76`.
- GPSD release/tag signing fingerprint:
  `4294517B6DE2093E930EBAE3AEFDB88FB63FB83B`; primary fingerprint:
  `1256D5A74A01B8145593C41EADA54A78FC147EEE`.

Both archive signatures passed gpgv with an explicit exported signer keyring;
both annotated Git tags passed git verify-tag with matching signing keys.
All 688 NTPsec tracked release files match tagged Git blobs. All 795 GPSD
tracked release files present in the archive match; seven omitted Git files
are CI/ignore files and two contrib AIS samples. Release-only files are generated
manuals, plus GPSD packaging files. No tracked source file differs. Exact tag
objects, commits, keys, signatures, full comparisons and logs are retained in
private source-selection evidence.

Trust bootstrap uses HTTPS publisher/project identity and published signed-tag
issuer identity. NTPsec publishes its key directly beside releases. GPSD's
official site links its GitLab project; its signed release tag identifies the
signing fingerprint, retrieved from keys.openpgp.org and verified against both
tag and archive. Savannah's maintainer-key endpoints timed out; no successful
maintainer-key-list or independent out-of-band certification is claimed.
The initial public-key import reported sandbox gpg-agent errors, although public
keys were imported. Final archive verification used agent-free gpgv and both
tag verifications completed with status zero; the original errors remain logged.

Primary sources:

- [NTPsec release index and signing keys](https://ftp.ntpsec.org/pub/releases/)
- [NTPsec selected tag](https://gitlab.com/NTPsec/ntpsec/-/tags/NTPsec_1_2_5)
- [GPSD release index](https://download.savannah.gnu.org/releases/gpsd/)
- [GPSD selected tag](https://gitlab.com/gpsd/gpsd/-/tags/release-3.27.5)
- [GPSD project identity](https://gpsd.io/)

## Release-specific build review

The signed release archives have top directories and no Git PAX commit comment.
NTPsec also contains a legitimate include/PIVOT.h link to ../PIVOT.h. Corrected
clockmaker to accept a hash-bound publisher archive with an explicit root and
internal links to archive regular files; absolute/escaping/broken links,
hardlinks, duplicate names and unexpected roots remain rejected. Both actual
signed archives passed local extraction through the corrected helper. Commit
binding is established by signature/tag/blob review, not an invented PAX field.

NTPsec 1.2.5 defines the waf check target and forces rerunning tests there.
Its buildprep names build-essential, bison, OpenSSL, capability/seccomp and
Python development inputs for Debian. It also suggests optional mDNS and
unversioned-Python aliases; neither is selected. Explicit Python 3 invocations
and generated shebangs avoid creating a global python alias.

GPSD 3.27.5 uses SCons and defines timeservice/magic_hat. Its timeservice preset
disables other default-enabled features unless explicitly selected, including
SHM export, Python and clients. Retain those explicitly for this plan. NMEA0183
is always built; the old guide's nmea0183/ublox/mtk3301/fixed_port_speed/
fixed_stop_bits arguments are not declared build options in this release.
Do not pass them and mistake an ignored argument for configured hardware.
The Uputronics UART requirement is 115200 baud. Enforce GPSD's supported runtime
`-s 115200` and checked `stty` initialization in the modernized supervisor;
do not pass `fixed_port_speed=115200` to SCons. The device path and receiver
bring-up still require target evidence.

Proposed features, to bind in the later build profile:

- NTPsec: SHM refclock matching the observed GPS SHM(0)/PPS SHM(1) arrangement;
  OpenSSL/NTS, supported privilege-drop/sandbox inputs, generated manual pages,
  no HTML build. Configure --refclock=shm, --disable-doc and --enable-manpage.
- GPSD: timeservice=yes, magic_hat=yes, shm_export=yes, gpsdclients=yes,
  python=yes, ncurses=yes and manbuild=yes. Explicitly disable Qt, GUI clients,
  package systemd/socket integration, D-Bus, USB and Bluetooth for this UART
  time-service build. These build choices do not select a GPIO/device or
  authorize service/network changes.

APT resolution roots for this feature set are build-essential, bison, m4,
pkg-config, python3-dev, scons, libssl-dev, libcap-dev, libseccomp-dev,
libncurses-dev, asciidoctor and python3-serial. The latter supports source
serial diagnostics; it is not an APT GPSD client module. pps-tools/i2c-tools
remain the separate diagnostic group. Native resolution must retain complete
transitive and recommended package/library versions and trusted archive hashes;
these names do not establish installation readiness. No NTPsec/GPSD application
or python3-gps root is selected.

## Python, libraries and remaining inputs

Do not guess the target's Python minor version or import directories. The next
preflight records executable/version, sys.path, sysconfig purelib/platlib and
extension suffix after package verification. Publisher build profiles require
that observed interpreter/version and an explicit local module directory.
Clockmaker derives both GPSD target_python/python_shebang/python_libdir and
NTPsec pythondir/pythonarchdir/pyshebang from that binding. During NTPsec build,
only the staged source GPSD Python directory is added to PYTHONPATH. APT GPSD
modules and pip mutations of Debian's managed interpreter remain excluded.

NTPsec's INSTALL warns that automatic /usr/local Python placement can fall
back into /usr/lib when its directory is missing; explicit paths avoid that
ambiguity. GPSD permits explicit python_libdir. Verify both staged module trees,
native NTP extension ABI and installed imports before accepting the applications.
Trusted APT resolution supplies selected runtime-library packages; later build/
installation acceptance must prove actual binary linkage and any needed ldconfig
effect. No dynamic-library cache change is included in metadata resolution.

The next operation is
[source-prerequisite metadata resolution](source-prerequisites-resolution-operation.md),
not a source build. Exact prerequisite versions, runtime UID/GID, GPIO/RTC/UART
device, remaining service arguments, executable build profile and installation bundle
remain held for target evidence and separate approvals.
