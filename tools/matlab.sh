#!/usr/bin/env bash
set -euo pipefail
# Переменная позволяет выбрать другую установку без изменения проекта.
matlab_root="${MATLAB_ROOT:-}"
if [[ -z "$matlab_root" ]]; then
  matlab_executable="$(command -v matlab || true)"
  if [[ -n "$matlab_executable" ]]; then
    matlab_root="$(dirname -- "$(dirname -- "$(readlink -f -- "$matlab_executable")")")"
  else
    matlab_root="$HOME/MATLAB/R2020b"
  fi
fi
if [[ ! -x "$matlab_root/bin/matlab" ]]; then
  printf 'MATLAB executable not found: %s/bin/matlab\n' "$matlab_root" >&2
  exit 1
fi
# Системная FreeType устраняет конфликт старой библиотеки MATLAB с новым HarfBuzz.
# Настройка действует только для этого запуска и отключается через MATLAB_SYSTEM_FREETYPE=0.
system_freetype=/usr/lib/x86_64-linux-gnu/libfreetype.so.6
if [[ "${MATLAB_SYSTEM_FREETYPE:-1}" == 1 && "$matlab_root" == */R2020b && -f "$system_freetype" ]]; then
  export LD_PRELOAD="$system_freetype${LD_PRELOAD:+:$LD_PRELOAD}"
fi
exec "$matlab_root/bin/matlab" "$@"
