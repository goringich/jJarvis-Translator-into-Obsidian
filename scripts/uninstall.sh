#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${OVV_CONFIG_PATH:-$HOME/.config/obsidian-voice-vocab/config.toml}"
UNIT_PATH="$HOME/.config/systemd/user/obsidian-voice-vocab.service"
REMOVE_VENV=0
REMOVE_CONFIG=0

for arg in "$@"; do
  case "$arg" in
    --remove-venv)
      REMOVE_VENV=1
      ;;
    --remove-config)
      REMOVE_CONFIG=1
      ;;
    *)
      printf 'Unknown argument: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

systemctl --user disable --now obsidian-voice-vocab.service >/dev/null 2>&1 || true
rm -f "$UNIT_PATH"
systemctl --user daemon-reload

if [[ "$REMOVE_VENV" == "1" ]]; then
  rm -rf "$PROJECT_DIR/.venv"
fi

if [[ "$REMOVE_CONFIG" == "1" ]]; then
  rm -f "$CONFIG_PATH"
fi

printf 'Uninstalled obsidian-voice-vocab systemd user service.\n'
printf 'Dictionary files in the Obsidian vault were not removed.\n'

