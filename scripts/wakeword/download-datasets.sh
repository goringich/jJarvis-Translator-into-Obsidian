#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="${OVV_WAKEWORD_DATA_ROOT:-$HOME/.cache/obsidian-voice-vocab/wakeword/datasets}"
SPEECH_COMMANDS_DIR="$DATA_ROOT/speech_commands_v0.02"
SPEECH_COMMANDS_ARCHIVE="$DATA_ROOT/speech_commands_v0.02.tar.gz"
SPEECH_COMMANDS_URL="https://storage.googleapis.com/download.tensorflow.org/data/speech_commands_v0.02.tar.gz"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd tar

mkdir -p "$DATA_ROOT"
if [[ -d "$SPEECH_COMMANDS_DIR/_background_noise_" ]]; then
  printf 'Google Speech Commands already extracted: %s\n' "$SPEECH_COMMANDS_DIR"
  exit 0
fi

printf 'Downloading Google Speech Commands v0.02 to %s\n' "$SPEECH_COMMANDS_ARCHIVE"
curl -L --fail --continue-at - --output "$SPEECH_COMMANDS_ARCHIVE" "$SPEECH_COMMANDS_URL"

mkdir -p "$SPEECH_COMMANDS_DIR"
tar -xzf "$SPEECH_COMMANDS_ARCHIVE" -C "$SPEECH_COMMANDS_DIR"
printf 'Dataset ready: %s\n' "$SPEECH_COMMANDS_DIR"
