#!/usr/bin/env bash
set -euo pipefail
# Находим корень, не завися от текущего рабочего каталога.
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
while [[ ! -f "$root/tools/run_research.py" ]]; do
  [[ "$root" != / ]] || { printf 'Project root not found\n' >&2; exit 1; }
  root="$(dirname -- "$root")"
done
exec python3 "$root/tools/run_research.py" --suite hdl --workspace 'filters/windowed_sinc' "$@"
