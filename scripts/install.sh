#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${OVV_CONFIG_PATH:-$HOME/.config/obsidian-voice-vocab/config.toml}"
CONFIG_DIR="$(dirname -- "$CONFIG_PATH")"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_PATH="$UNIT_DIR/obsidian-voice-vocab.service"
ENABLE_SERVICE="${OVV_ENABLE_SERVICE:-1}"
START_SERVICE="${OVV_START_SERVICE:-1}"
DOWNLOAD_MODELS="${OVV_DOWNLOAD_MODELS:-0}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd python3
need_cmd systemctl

if ! pacman -Qi portaudio >/dev/null 2>&1; then
  printf 'Warning: Arch package "portaudio" is not installed. Install it with: sudo pacman -S portaudio\n' >&2
fi

python3 -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$PROJECT_DIR/.venv/bin/python" -m pip install -e "$PROJECT_DIR"
chmod +x "$PROJECT_DIR/scripts/run-daemon-session.sh"

install -d "$CONFIG_DIR"
if [[ ! -f "$CONFIG_PATH" ]]; then
  install -m 0644 "$PROJECT_DIR/config.example.toml" "$CONFIG_PATH"
  printf 'Created config: %s\n' "$CONFIG_PATH"
else
  printf 'Keeping existing config: %s\n' "$CONFIG_PATH"
fi

if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
  "$PROJECT_DIR/scripts/download-models.sh"
fi

"$PROJECT_DIR/.venv/bin/obsidian-voice-vocab" --config "$CONFIG_PATH" --foreground init

install -d "$UNIT_DIR"
sed \
  -e "s#@PROJECT_DIR@#$PROJECT_DIR#g" \
  -e "s#@CONFIG_PATH@#$CONFIG_PATH#g" \
  "$PROJECT_DIR/packaging/systemd/obsidian-voice-vocab.service.in" > "$UNIT_PATH"

systemctl --user daemon-reload
if [[ "$ENABLE_SERVICE" == "1" ]]; then
  systemctl --user enable obsidian-voice-vocab.service
fi
if [[ "$START_SERVICE" == "1" ]]; then
  systemctl --user restart obsidian-voice-vocab.service
fi

printf 'Installed obsidian-voice-vocab.\n'
printf 'Config: %s\n' "$CONFIG_PATH"
printf 'Unit:   %s\n' "$UNIT_PATH"
printf 'Logs:   journalctl --user -u obsidian-voice-vocab.service -f\n'
