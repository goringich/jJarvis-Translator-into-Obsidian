# Obsidian Voice Vocabulary

Local Arch Linux daemon for adding English words to an Obsidian vault by voice.

The service listens for `Hello Obsidian` with a lightweight local Vosk grammar recognizer. Every wake hit is then re-checked on a short buffered audio clip with `faster-whisper`, so false positives do not immediately open the active recording window. Only after that verification step it records a short microphone window and runs active speech recognition for the target word. The recognized word is written into deterministic A-Z markdown files in the vault immediately, and the slower LLM translation/example enrichment now runs in the background.

After the verified wake phrase, recording starts immediately and is then trimmed/stopped using WebRTC VAD. This avoids clipping the first syllable while still preventing long silence tails from going into Whisper. Wake verification also now uses a shorter clip plus a prompted Whisper pass, which reduces the chance that random trailing speech dominates the verification transcript.

## Why This Stack

- Wake word: Vosk grammar mode plus Whisper verification, because it stays offline and cheap in the background, but adds a stronger second check on each wake candidate without running a heavy model continuously.
- Active STT: faster-whisper, because Whisper quality is better for the short post-wake window and the model is loaded lazily.
- LLM: adapter-based local HTTP integration. The default is Ollama with `gpt-oss:20b`; OpenAI-compatible endpoints are also supported.
- Service model: `systemd --user`, because this is a desktop microphone workflow and should run in the logged-in user session with PipeWire/PortAudio access.

Checked alternatives before choosing this:

- openWakeWord: good offline wake-word framework, but `Hello Obsidian` requires a trained/custom model.
- sherpa-onnx KWS: strong offline stack with many deployment targets, but it is a larger migration than this project currently needs.
- Picovoice Porcupine: strong wake-word engine, but custom keywords and access-key flow add friction for a fully local default.
- Continuous Whisper: simpler to code, but too heavy for an always-on daemon.
- Silero VAD: stronger neural VAD than raw WebRTC VAD, but not yet needed after the current wake/recording tuning.

Relevant upstream projects:

- Vosk: <https://github.com/alphacep/vosk-api>
- faster-whisper: <https://github.com/SYSTRAN/faster-whisper>
- openWakeWord: <https://github.com/dscripka/openWakeWord>
- sherpa-onnx: <https://github.com/k2-fsa/sherpa-onnx>
- Silero VAD: <https://github.com/snakers4/silero-vad>

## Project Layout

```text
obsidian-voice-vocab/
  obsidian_voice_vocab/
    audio.py            # microphone capture, wake listener, STT
    cli.py              # CLI entry point
    config.py           # TOML config dataclasses
    daemon.py           # main service loop
    feedback.py         # Hyprland notification/sound feedback
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

The default active speech recognizer runs faster-whisper on CPU with `int8`. That avoids accidental CUDA loading failures such as missing `libcublas.so.12`. If CUDA is intentionally configured later, tune `whisper_device` and `whisper_compute_type` in the config.

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
- `wake.phrase_variants`: extra local grammar phrases such as `hey obsidian`
- `wake.model_path`: local Vosk model path
- `wake.verify_with_stt`: run a second Whisper verification pass on the wake clip
- `wake.verify_buffer_seconds`: how much recent wake audio is kept for verification
- `wake.verify_post_roll_seconds`: extra tail kept after the wake hit before verification
- `wake.cooldown_seconds`: reject clustered duplicate wake hits
- `audio.device`: input device name/index. On this machine it stays empty and PipeWire default source is set to HyperX SoloCast; raw ALSA index `0` rejects 16000 Hz.
- `audio.active_window_seconds`: post-wake recording window
- `audio.speech_*`: early-stop and trim settings for the post-wake speech window
- `words.max_candidates`: maximum distinct vocabulary words accepted from one active recording. Default `1` rejects noisy multi-word recognitions instead of saving the wrong word.
- `words.singularize_simple_plurals`: converts simple plural recognitions such as `elephants` to `elephant`
- `feedback.hyprctl_notify`: safe Hyprland popup feedback without `swaync`
- `feedback.sound`: short local sounds for ready/wake/success/error
- `feedback.notify_send`: disabled by default because it can activate the notification daemon
- `feedback.rejection_interval_seconds`: rate limit for noisy false-wake popups
- `feedback.dedupe_window_seconds`: suppress identical repeated notifications
- `feedback.show_wake_rejections`: keep false-wake popups visible but throttled; set `false` to log only
- `stt.whisper_model`: faster-whisper model name or local model path
- `llm.provider`: `ollama`, `openai-compatible`, `openclaw`, or `none`
- `llm.endpoint`: local endpoint URL
- `llm.model`: default `gpt-oss:20b`
- `duplicates.overwrite_existing`: duplicate update policy

Behavior note:

- voice mode now writes the recognized word immediately with `Status: queued` and lets the LLM refine it in the background
- hotkey/selection mode can do the same with `--no-generate`, so the visible save path stays sub-second even when `gpt-oss:20b` is slow

## Foreground Debug Run

Initialize files:

```bash
.venv/bin/obsidian-voice-vocab --foreground init
```

Check dependencies and audio devices:

```bash
.venv/bin/obsidian-voice-vocab --foreground doctor --devices
```

Check that the configured microphone is producing signal:

```bash
.venv/bin/obsidian-voice-vocab --foreground mic-test --seconds 3
```

Wait for one wake phrase and print both the cheap detector result and the Whisper verification result:

```bash
.venv/bin/obsidian-voice-vocab --foreground wake-test
```

Record and transcribe the same active speech window used after wake, without writing to Obsidian:

```bash
.venv/bin/obsidian-voice-vocab --foreground record-test
```

If the active recognizer still feels weak on single words, start by checking that `whisper_model` is at least `small.en` in the config. The daemon now also runs a second, more focused Whisper pass for one-word vocabulary commands when the first transcript is too verbose.

Test local feedback without using the notification daemon:

```bash
.venv/bin/obsidian-voice-vocab --foreground feedback-test
```

Test the local LLM without writing to Obsidian:

```bash
.venv/bin/obsidian-voice-vocab --foreground llm-test sustainable
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

Add the currently selected word from Wayland and open the saved entry in Obsidian:

```bash
.venv/bin/obsidian-voice-vocab --foreground add-selection --clipboard auto --open-obsidian
```

The helper script used by the Hyprland hotkey does the same:

```bash
./scripts/add-selected-word.sh
```

If the Obsidian community plugin `obsidian-advanced-uri` is installed, the command jumps to the exact saved word block. Otherwise it falls back to opening the correct `English/<LETTER>.md` file.

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

## Desktop Feedback

This machine previously disabled `swaync` through session startup guard files after it appeared near Hyprland/NVIDIA crash windows. The service therefore does not re-enable `swaync` and keeps `notify-send` disabled by default.

Feedback uses:

- `hyprctl notify` for Hyprland-native popups
- `pw-play` or `paplay` for local sound cues

The service emits feedback when it starts listening, detects the wake phrase, rejects a false wake, rejects speech, hits an error, or writes a word successfully. Rejection popups are rate-limited so background audio cannot flood Hyprland notifications.

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
   ^ovv-sustainable
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
{"translation":"<short Russian translation>","example":"<one short natural B1-B2 English sentence containing the exact word>"}
```

The parser accepts strict JSON, key-value output, or two plain lines. It rejects examples that are not English, do not contain the exact word, or only talk about studying the word instead of showing its meaning in context. If the local endpoint is unavailable, the daemon logs the error and writes the word with fallback fields:

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
