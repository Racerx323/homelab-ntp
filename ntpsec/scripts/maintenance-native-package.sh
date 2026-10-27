#!/usr/bin/env bash
# One native APT invocation in the sealed private stage; systemd owns its lifetime.
set -Eeuo pipefail
export LC_ALL=C PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077
[[ $EUID -eq 0 ]]
python3 -I -B - <<'PY'
import json,pathlib,time
s=json.loads(pathlib.Path('spec.json').read_text())
assert str(pathlib.Path.cwd()) == s['stage']
assert time.time() < s['expires_epoch']
PY
sha256sum --check payloads.sha256
set -C
: >package-intent
set +C
record_exit() {
    local result=$?
    printf '%s\n' "$result" >package-exit-status
    exit "$result"
}
trap record_exit EXIT
export APT_CONFIG="$PWD/apt.conf"
export DEBIAN_FRONTEND=noninteractive APT_LISTCHANGES_FRONTEND=none NEEDRESTART_MODE=l
mapfile -t packages <package-paths.txt
/usr/bin/apt-get --no-download --no-remove --no-install-recommends --no-install-suggests -y install "${packages[@]}"
