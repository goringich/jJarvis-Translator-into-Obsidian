#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:?config path is required}"
SESSION_ENV="${HOME}/.config/hypr/session.env"
UID_VALUE="$(id -u)"

load_session_env() {
  if [[ -f "$SESSION_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$SESSION_ENV"
    set +a
  fi
}

discover_wayland_env() {
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${UID_VALUE}}"
  if [[ -z "${WAYLAND_DISPLAY:-}" && -d "$XDG_RUNTIME_DIR" ]]; then
    for socket in "$XDG_RUNTIME_DIR"/wayland-*; do
      if [[ -S "$socket" ]]; then
        export WAYLAND_DISPLAY="$(basename -- "$socket")"
        break
      fi
    done
  fi
  if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" && -d "$XDG_RUNTIME_DIR/hypr" ]]; then
    local latest=""
    local newest=0
    local dir mtime
    for dir in "$XDG_RUNTIME_DIR"/hypr/*; do
      [[ -d "$dir" ]] || continue
      mtime="$(stat -c %Y "$dir" 2>/dev/null || printf '0')"
      if (( mtime >= newest )); then
        newest="$mtime"
        latest="$(basename -- "$dir")"
      fi
    done
    if [[ -n "$latest" ]]; then
      export HYPRLAND_INSTANCE_SIGNATURE="$latest"
    fi
  fi
  export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-Hyprland}"
  export XDG_SESSION_TYPE="${XDG_SESSION_TYPE:-wayland}"
}

wait_for_session() {
  local attempt
  for attempt in $(seq 1 120); do
    load_session_env
    discover_wayland_env
    if [[ -n "${XDG_RUNTIME_DIR:-}" && -n "${WAYLAND_DISPLAY:-}" ]]; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

if ! wait_for_session; then
  printf 'obsidian-voice-vocab: Wayland session environment did not become ready; exiting without restart loop\n' >&2
  exit 0
fi

exec "$PROJECT_DIR/.venv/bin/obsidian-voice-vocab" --config "$CONFIG_PATH" daemon
