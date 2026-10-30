#!/usr/bin/env bash
set -euo pipefail
# Локальный запуск без изменения конфигурации установленного симулятора.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/run_hdl.py" "$@"
