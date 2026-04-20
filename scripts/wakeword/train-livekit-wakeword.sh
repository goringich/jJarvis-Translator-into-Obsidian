#!/usr/bin/env bash
set -euo pipefail

CONFIG="${OVV_WAKEWORD_TRAIN_CONFIG:-training/wakeword/hello_obsidian.yaml}"
MODEL_DIR="${OVV_WAKEWORD_MODEL_DIR:-training/wakeword/models}"
TRAIN_VENV="${OVV_WAKEWORD_TRAIN_VENV:-.venv-wakeword}"

if ! command -v livekit-wakeword >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.11 "$TRAIN_VENV"
    "$TRAIN_VENV/bin/python" -m pip install --upgrade pip
    "$TRAIN_VENV/bin/python" -m pip install -e ".[train,wakeword]"
    export PATH="$PWD/$TRAIN_VENV/bin:$PATH"
  else
    printf 'Missing livekit-wakeword. Install with Python 3.11: python -m pip install -e ".[train,wakeword]"\n' >&2
    exit 1
  fi
fi

mkdir -p "$MODEL_DIR"
livekit-wakeword setup
livekit-wakeword run "$CONFIG"

found_model="$(find training/wakeword/output -type f \( -name '*.onnx' -o -name '*.tflite' \) | sort | tail -n 1 || true)"
if [[ -z "$found_model" ]]; then
  printf 'Training finished but no ONNX/TFLite model was found under training/wakeword/output.\n' >&2
  exit 2
fi

extension="${found_model##*.}"
cp "$found_model" "$MODEL_DIR/hello_obsidian.$extension"
printf 'Trained wake model copied to: %s\n' "$MODEL_DIR/hello_obsidian.$extension"
