#!/usr/bin/env bash
set -euo pipefail

MODEL_ROOT="${OVV_MODEL_ROOT:-$HOME/.local/share/obsidian-voice-vocab/models}"
MODEL_NAME="vosk-model-small-en-us-0.15"
MODEL_URL="https://alphacephei.com/vosk/models/${MODEL_NAME}.zip"
ARCHIVE="$MODEL_ROOT/${MODEL_NAME}.zip"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd unzip

mkdir -p "$MODEL_ROOT"
if [[ -d "$MODEL_ROOT/$MODEL_NAME" ]]; then
  printf 'Vosk model already exists: %s\n' "$MODEL_ROOT/$MODEL_NAME"
  exit 0
fi

curl -L --fail --output "$ARCHIVE" "$MODEL_URL"
unzip -q "$ARCHIVE" -d "$MODEL_ROOT"
rm -f "$ARCHIVE"
printf 'Downloaded Vosk wake/STT fallback model: %s\n' "$MODEL_ROOT/$MODEL_NAME"

