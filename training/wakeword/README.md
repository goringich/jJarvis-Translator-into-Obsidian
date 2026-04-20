# Wakeword Training

The current Vosk grammar wake detector is a cheap fallback, not a strong wake-word model. For a low-latency desktop assistant the better target is a small on-device wake model, then Whisper only after a real wake hit.

## Chosen Stack

- Runtime path in this project: `wake.provider = "openwakeword"` with a local `hello_obsidian` model.
- Training path: `livekit-wakeword`, because it wraps the openWakeWord-style pipeline behind a YAML config and exports ONNX models.
- Negative speech/noise data: Google Speech Commands v0.02, downloaded into `~/.cache/obsidian-voice-vocab/wakeword/datasets`.

## Local Training

Install OS packages on Arch:

```bash
scripts/wakeword/install-training-deps-arch.sh
```

Install Python training extras:

```bash
python -m pip install -e ".[train,wakeword]"
```

Download the public negative dataset:

```bash
scripts/wakeword/download-datasets.sh
```

Train and export:

```bash
scripts/wakeword/train-livekit-wakeword.sh
```

Copy the exported model into the runtime model directory:

```bash
mkdir -p ~/.local/share/obsidian-voice-vocab/models
cp training/wakeword/models/hello_obsidian.onnx ~/.local/share/obsidian-voice-vocab/models/hello_obsidian.onnx
```

Then switch the user config:

```toml
[wake]
provider = "openwakeword"
openwakeword_model_path = "~/.local/share/obsidian-voice-vocab/models/hello_obsidian.onnx"
openwakeword_threshold = 0.55
openwakeword_trigger_level = 2
```

## CI/CD

`.github/workflows/ci.yml` runs unit tests, Python compilation, and shell syntax checks on every push/PR.

`.github/workflows/wakeword-training.yml` is intentionally `workflow_dispatch` and `self-hosted`. Training depends on multi-GB datasets and is not a good fit for a small GitHub-hosted runner.
