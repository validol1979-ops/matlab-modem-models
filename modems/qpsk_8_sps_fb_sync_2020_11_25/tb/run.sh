#!/usr/bin/env bash
set -euo pipefail
# Скрипт запускается из любого каталога.
modem_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(cd -- "$modem_dir/../.." && pwd)"
exec python3 "$project_dir/tools/run_hdl.py" --modem "$(basename -- "$modem_dir")" "$@"
