#!/bin/bash
set -Eeuo pipefail
test_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
python3 -I "$test_dir/test_inspect_node.py"
python3 -I "$test_dir/test_pre_rebuild.py"
exec python3 -I "$test_dir/test_inspect_trixie.py"
