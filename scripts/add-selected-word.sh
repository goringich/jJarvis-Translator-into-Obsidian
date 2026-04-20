#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${OVV_CONFIG_PATH:-$HOME/.config/obsidian-voice-vocab/config.toml}"
CLI="$PROJECT_DIR/.venv/bin/obsidian-voice-vocab"
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/obsidian-voice-vocab"
ENRICH_LOG="$LOG_DIR/enrich.log"

notify() {
  local icon="$1"
  local color="$2"
  local message="$3"
  if command -v hyprctl >/dev/null 2>&1; then
    hyprctl notify "$icon" 4000 "$color" "Voice Vocabulary: $message" >/dev/null 2>&1 || true
  fi
}

extract_word() {
  local text="$1"
  printf '%s\n' "$text" | sed -n 's/^\([a-z][a-z-]*\) -> .*$/\1/p' | head -n1
}

run_add() {
  "$CLI" \
    --config "$CONFIG_PATH" \
    "$@"
}

enqueue_enrich() {
  local word="$1"
  mkdir -p "$LOG_DIR"
  nohup "$CLI" --config "$CONFIG_PATH" enrich-word "$word" >>"$ENRICH_LOG" 2>&1 </dev/null &
}

run_add_with_feedback() {
  local output
  if ! output="$(run_add "$@" 2>&1)"; then
    printf '%s\n' "$output" >&2
    return 1
  fi
  printf '%s\n' "$output"
  local word
  word="$(extract_word "$output")"
  if [[ -n "$word" ]]; then
    notify 5 "rgba(9ece6aff)" "Added: $word"
    enqueue_enrich "$word"
  else
    notify 5 "rgba(9ece6aff)" "Word added"
  fi
}

if initial_output="$(run_add_with_feedback add-selection --clipboard auto --no-generate --open-obsidian "$@" 2>&1)"; then
  printf '%s\n' "$initial_output"
  exit 0
fi

printf '%s\n' "$initial_output" >&2
notify 3 "rgba(eb6f92ff)" "Failed: ${initial_output//$'\n'/ }"
exit 1
