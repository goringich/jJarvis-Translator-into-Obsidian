from __future__ import annotations

from pathlib import Path
import argparse
import logging
import sys

from .audio import AudioError, AudioRecorder, list_audio_devices
from .config import AppConfig, default_config_path
from .daemon import VoiceVocabularyDaemon
from .feedback import Feedback
from .llm import build_adapter, generate_with_fallback
from .logging_setup import setup_logging
from .markdown_store import DictionaryStore, VocabEntry
from .normalizer import WordExtractionError, extract_word, normalize_word


LOG = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
  parser = build_parser()
  args = parser.parse_args(argv)
  try:
    config = AppConfig.load(args.config)
    setup_logging(config.runtime.log_level, config.runtime.log_file, foreground=args.foreground)
    return int(args.func(args, config) or 0)
  except KeyboardInterrupt:
    return 130
  except Exception as exc:
    setup_logging("ERROR", None, foreground=True)
    LOG.error("%s", exc)
    return 1


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(prog="obsidian-voice-vocab")
  parser.add_argument("--config", type=Path, default=default_config_path(), help="Path to config.toml.")
  parser.add_argument("--foreground", action="store_true", help="Also print logs to stdout.")

  subparsers = parser.add_subparsers(dest="command", required=True)

  init_parser = subparsers.add_parser("init", help="Create dictionary folder and A-Z files.")
  init_parser.set_defaults(func=cmd_init)

  doctor_parser = subparsers.add_parser("doctor", help="Check local configuration and dependencies.")
  doctor_parser.add_argument("--devices", action="store_true", help="Print PortAudio input/output device list.")
  doctor_parser.set_defaults(func=cmd_doctor)

  mic_parser = subparsers.add_parser("mic-test", help="Measure configured microphone level for a few seconds.")
  mic_parser.add_argument("--seconds", type=float, default=3.0, help="Measurement duration.")
  mic_parser.set_defaults(func=cmd_mic_test)

  feedback_parser = subparsers.add_parser("feedback-test", help="Show safe desktop feedback without enabling swaync.")
  feedback_parser.set_defaults(func=cmd_feedback_test)

  add_parser = subparsers.add_parser("add-word", help="Add or update one word without microphone.")
  add_parser.add_argument("text", help="Word or short phrase; the first valid English word is used.")
  add_parser.add_argument("--translation", default="", help="Manual Russian translation. Skips LLM only if --example is also supplied or --no-generate is used.")
  add_parser.add_argument("--example", default="", help="Manual English example sentence.")
  add_parser.add_argument("--no-generate", action="store_true", help="Do not call the local LLM.")
  add_parser.add_argument("--overwrite", action="store_true", help="Override duplicate policy for this command.")
  add_parser.set_defaults(func=cmd_add_word)

  daemon_parser = subparsers.add_parser("daemon", help="Run wake-word listener and vocabulary daemon.")
  daemon_parser.add_argument("--once", action="store_true", help="Exit after one activation cycle.")
  daemon_parser.set_defaults(func=cmd_daemon)

  return parser


def cmd_init(args: argparse.Namespace, config: AppConfig) -> int:
  store = DictionaryStore(config)
  store.initialize()
  LOG.info("dictionary initialized path=%s", config.dictionary_path)
  return 0


def cmd_doctor(args: argparse.Namespace, config: AppConfig) -> int:
  store = DictionaryStore(config)
  LOG.info("config loaded vault=%s dictionary=%s", config.vault.path, config.dictionary_path)
  LOG.info("dictionary folder exists=%s", config.dictionary_path.exists())
  LOG.info("audio device=%s sample_rate=%s channels=%s", config.audio.device, config.audio.sample_rate, config.audio.channels)
  wake_phrases = tuple(dict.fromkeys((*config.wake.phrase_variants, config.wake.phrase)))
  LOG.info("wake provider=%s phrases=%s model_path=%s exists=%s", config.wake.provider, wake_phrases, config.wake.model_path, config.wake.model_path.exists())
  LOG.info("stt provider=%s whisper_model=%s", config.stt.provider, config.stt.whisper_model)
  LOG.info("llm provider=%s endpoint=%s model=%s", config.llm.provider, config.llm.endpoint, config.llm.model)
  LOG.info("feedback hyprctl=%s sound=%s notify_send=%s", config.feedback.hyprctl_notify, config.feedback.sound, config.feedback.notify_send)
  missing = []
  try:
    import sounddevice
    LOG.info("sounddevice available version=%s", getattr(sounddevice, "__version__", "unknown"))
  except Exception as exc:
    missing.append(f"sounddevice: {exc}")
  try:
    import vosk
    LOG.info("vosk available module=%s", vosk.__name__)
  except Exception as exc:
    missing.append(f"vosk: {exc}")
  try:
    import faster_whisper
    LOG.info("faster-whisper available module=%s", faster_whisper.__name__)
  except Exception as exc:
    missing.append(f"faster-whisper: {exc}")
  if args.devices:
    try:
      print(list_audio_devices())
    except AudioError as exc:
      missing.append(str(exc))
  store.initialize()
  if missing:
    for item in missing:
      LOG.error("missing dependency: %s", item)
    return 2
  return 0


def cmd_mic_test(args: argparse.Namespace, config: AppConfig) -> int:
  seconds = max(0.5, float(args.seconds))
  rms, peak, samples = AudioRecorder(config).measure_level(seconds)
  LOG.info(
    "microphone level device=%s seconds=%.1f samples=%s rms=%.4f peak=%.4f",
    config.audio.device,
    seconds,
    samples,
    rms,
    peak,
  )
  print(f"device={config.audio.device} seconds={seconds:.1f} samples={samples} rms={rms:.4f} peak={peak:.4f}")
  if peak < 0.002:
    LOG.warning("microphone signal is very low; check selected input device, mute state, and PipeWire routing")
    return 3
  return 0


def cmd_feedback_test(args: argparse.Namespace, config: AppConfig) -> int:
  feedback = Feedback(config)
  feedback.ready()
  feedback.wake()
  feedback.success("example")
  return 0


def cmd_add_word(args: argparse.Namespace, config: AppConfig) -> int:
  store = DictionaryStore(config)
  store.initialize()
  try:
    extraction = extract_word(
      args.text,
      command_words=config.words.command_words,
      allow_hyphenated=config.words.allow_hyphenated,
    )
    word = extraction.word
  except WordExtractionError:
    word = normalize_word(args.text)

  translation = args.translation
  example = args.example
  status = "manual"
  if not args.no_generate and not (translation and example):
    adapter = build_adapter(config.llm)
    generated = generate_with_fallback(adapter, config.llm, word)
    translation = translation or generated.translation
    example = example or generated.example
    status = generated.status

  result = store.add_or_update(
    VocabEntry(
      word=word,
      translation=translation,
      example=example,
      status=status,
    ),
    overwrite_existing=args.overwrite or None,
  )
  LOG.info(
    "word written word=%s path=%s created=%s updated=%s total=%s",
    result.word,
    result.path,
    result.created,
    result.updated,
    result.count,
  )
  print(f"{result.word} -> {result.path}")
  return 0


def cmd_daemon(args: argparse.Namespace, config: AppConfig) -> int:
  daemon = VoiceVocabularyDaemon(config)
  daemon.run(once=args.once)
  return 0


if __name__ == "__main__":
  sys.exit(main())
