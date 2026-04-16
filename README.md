# Obsidian Voice Vocabulary

Local Arch Linux daemon for adding English words to an Obsidian vault by voice.

The service listens for `Hello Obsidian` with a lightweight local Vosk grammar recognizer. Only after the wake phrase it records a short microphone window and runs active speech recognition with `faster-whisper`. The recognized word is normalized, enriched through a local LLM endpoint, and written into deterministic A-Z markdown files in the vault.

## Why This Stack

- Wake word: Vosk grammar mode, because it is offline, CPU-light, Linux-friendly, and can recognize the exact phrase `hello obsidian` without training a custom wake-word model.
- Active STT: faster-whisper, because Whisper quality is better for the short post-wake window and the model is loaded lazily.
- LLM: adapter-based local HTTP integration. The default is Ollama with `qwen2.5:1.5b`; OpenAI-compatible endpoints are also supported.
- Service model: `systemd --user`, because this is a desktop microphone workflow and should run in the logged-in user session with PipeWire/PortAudio access.

Checked alternatives before choosing this:

- openWakeWord: good offline wake-word framework, but `Hello Obsidian` requires a trained/custom model.
- Picovoice Porcupine: strong wake-word engine, but custom keywords and access-key flow add friction for a fully local default.
- Continuous Whisper: simpler to code, but too heavy for an always-on daemon.

Relevant upstream projects:

- Vosk: <https://github.com/alphacep/vosk-api>
- faster-whisper: <https://github.com/SYSTRAN/faster-whisper>
- openWakeWord: <https://github.com/dscripka/openWakeWord>

## Project Layout

```text
obsidian-voice-vocab/
  obsidian_voice_vocab/
    audio.py            # microphone capture, wake listener, STT
    cli.py              # CLI entry point
    config.py           # TOML config dataclasses
    daemon.py           # main service loop
    llm.py              # Ollama/OpenAI-compatible adapters
    markdown_store.py   # deterministic Obsidian markdown storage
    normalizer.py       # transcript and word normalization
  config.example.toml
  packaging/systemd/
  scripts/
  tests/
```

## Arch Linux Dependencies

Install system packages:

```bash
sudo pacman -S --needed python python-pip portaudio curl unzip
```

For NVIDIA/CUDA faster-whisper acceleration you can tune `whisper_device` and `whisper_compute_type` in the config. The default `auto` + `int8` is conservative.

## Install

From this directory:

```bash
./scripts/install.sh
```

The installer:

- creates `.venv`
- installs the Python package
- creates `~/.config/obsidian-voice-vocab/config.toml` from `config.example.toml` if missing
- initializes `/home/goringich/Desktop/Obsidian/English`
- creates `A.md` through `Z.md`
- installs and starts `~/.config/systemd/user/obsidian-voice-vocab.service`

To also download the small Vosk model during install:

```bash
OVV_DOWNLOAD_MODELS=1 ./scripts/install.sh
```

Or download it separately:

```bash
./scripts/download-models.sh
```

## Configuration

Main config:

```text
~/.config/obsidian-voice-vocab/config.toml
```

Important values:

- `vault.path`: Obsidian vault root
- `vault.dictionary_folder`: managed dictionary folder name
- `wake.phrase`: default `hello obsidian`
- `wake.model_path`: local Vosk model path
- `audio.device`: empty for default microphone, or a device name/index
- `audio.active_window_seconds`: post-wake recording window
- `stt.whisper_model`: faster-whisper model name or local model path
- `llm.provider`: `ollama`, `openai-compatible`, `openclaw`, or `none`
- `llm.endpoint`: local endpoint URL
- `llm.model`: default `qwen2.5:1.5b`
- `duplicates.overwrite_existing`: duplicate update policy

## Foreground Debug Run

Initialize files:

```bash
.venv/bin/obsidian-voice-vocab --foreground init
```

Check dependencies and audio devices:

```bash
.venv/bin/obsidian-voice-vocab --foreground doctor --devices
```

Run daemon in foreground:

```bash
.venv/bin/obsidian-voice-vocab --foreground daemon
```

Run one wake cycle and exit:

```bash
.venv/bin/obsidian-voice-vocab --foreground daemon --once
```

## Manual Test Without Microphone

```bash
.venv/bin/obsidian-voice-vocab --foreground add-word sustainable
```

Manual fields:

```bash
.venv/bin/obsidian-voice-vocab --foreground add-word sustainable \
  --translation "устойчивый" \
  --example "Sustainable habits can improve everyday life."
```

Skip LLM:

```bash
.venv/bin/obsidian-voice-vocab --foreground add-word sustainable --no-generate
```

## systemd User Service

Start:

```bash
systemctl --user start obsidian-voice-vocab.service
```

Enable autostart:

```bash
systemctl --user enable obsidian-voice-vocab.service
```

Restart:

```bash
systemctl --user restart obsidian-voice-vocab.service
```

Stop:

```bash
systemctl --user stop obsidian-voice-vocab.service
```

Logs:

```bash
journalctl --user -u obsidian-voice-vocab.service -f
```

File log:

```bash
tail -f ~/.local/state/obsidian-voice-vocab/daemon.log
```

## Markdown Format

Each letter file is fully regenerated in this stable format:

```markdown
# S

> Managed by obsidian-voice-vocab. Entry numbering is regenerated after each write.

<!-- ovv:begin -->

<!-- ovv:entry word="sustainable" -->
1. **sustainable**
   - Translation: устойчивый
   - Example: Sustainable habits can improve everyday life.
   - Status: generated
<!-- /ovv:entry -->

<!-- ovv:end -->
```

The HTML markers give the parser stable boundaries. The visible content remains readable in Obsidian. On every write the service reads existing entries, merges or updates the target word, sorts alphabetically, and rewrites the full file with fresh numbering.

Duplicate policy:

- `overwrite_existing = false`: keep existing non-empty translation/example, fill only missing fields.
- `overwrite_existing = true`: replace existing fields only when new values are non-empty.

## LLM Behavior

The prompt asks the local model for exactly two non-markdown lines:

```text
translation: <short Russian translation>
example: <one short natural B1-B2 English sentence containing the exact word>
```

The parser accepts strict key-value output, JSON, or two plain lines. If the local endpoint is unavailable, the daemon logs the error and writes the word with fallback fields:

- `Status: llm-failed`
- a built-in translation only when the tiny fallback dictionary knows the word
- otherwise empty translation/example

No cloud services are used by default.

## Tests

Run:

```bash
python -m unittest discover -s tests
```

Or with the venv:

```bash
.venv/bin/python -m unittest discover -s tests
```

## Uninstall

```bash
./scripts/uninstall.sh
```

This stops and removes only the user service. It does not delete dictionary files inside the Obsidian vault.

Optional cleanup:

```bash
./scripts/uninstall.sh --remove-venv --remove-config
```

