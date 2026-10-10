#!/bin/bash
set -Eeuo pipefail
test_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 -I -B "$test_dir/test_inspect_node.py"
python3 -I -B "$test_dir/test_pre_rebuild.py"
python3 -I -B "$test_dir/test_inspect_trixie.py"
python3 -I -B "$test_dir/test_resolve_trixie_packages.py"
python3 -I -B "$test_dir/test_metadata_elevation.py"
if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$test_dir/../templates/timeservice.service"
fi
exec python3 -I -B "$test_dir/test_clockmaker.py"
