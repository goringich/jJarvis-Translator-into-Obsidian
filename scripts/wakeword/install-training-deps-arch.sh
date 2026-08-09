#!/usr/bin/env bash
set -euo pipefail

if ! command -v pacman >/dev/null 2>&1; then
  printf 'This helper is for Arch Linux systems with pacman.\n' >&2
  exit 1
fi

sudo pacman -S --needed espeak-ng ffmpeg sox libsndfile portaudio
