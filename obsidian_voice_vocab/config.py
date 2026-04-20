from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os
import tomllib


ALPHABET = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


@dataclass(frozen=True)
class VaultConfig:
  path: Path = Path("/home/goringich/Desktop/Obsidian")
  dictionary_folder: str = "English"
  alphabet_files: tuple[str, ...] = tuple(f"{letter}.md" for letter in ALPHABET)


@dataclass(frozen=True)
class DuplicateConfig:
  overwrite_existing: bool = False


@dataclass(frozen=True)
class AudioConfig:
  sample_rate: int = 16000
  device: str | int | None = None
  channels: int = 1
  block_ms: int = 60
  active_window_seconds: float = 6.0
  speech_start_timeout_seconds: float = 4.0
  speech_silence_stop_seconds: float = 1.0
  speech_min_seconds: float = 0.35
  speech_pre_roll_ms: int = 240
  speech_start_blocks: int = 2
  speech_rms_threshold: float = 0.006
  speech_peak_threshold: float = 0.020
  speech_finish_grace_seconds: float = 0.45
  vad_mode: int = 2
  vad_frame_ms: int = 30


@dataclass(frozen=True)
class FeedbackConfig:
  hyprctl_notify: bool = True
  sound: bool = True
  notify_send: bool = False
  timeout_ms: int = 3500
  min_interval_seconds: float = 2.0
  rejection_interval_seconds: float = 30.0
  dedupe_window_seconds: float = 45.0
  show_wake_rejections: bool = False
  ready_sound: Path = Path("/usr/share/sounds/freedesktop/stereo/service-login.oga")
  wake_sound: Path = Path("/usr/share/sounds/freedesktop/stereo/message-new-instant.oga")
  success_sound: Path = Path("/usr/share/sounds/freedesktop/stereo/complete.oga")
  error_sound: Path = Path("/usr/share/sounds/freedesktop/stereo/dialog-warning.oga")


@dataclass(frozen=True)
class WakeConfig:
  phrase: str = "hello obsidian"
  phrase_variants: tuple[str, ...] = ("hello obsidian", "hey obsidian", "okay obsidian")
  provider: str = "vosk-grammar"
  model_path: Path = Path("~/.local/share/obsidian-voice-vocab/models/vosk-model-small-en-us-0.15")
  openwakeword_model_path: Path = Path("~/.local/share/obsidian-voice-vocab/models/hello_obsidian.onnx")
  openwakeword_threshold: float = 0.55
  openwakeword_trigger_level: int = 2
  require_exact_match: bool = True
  partial_confirmation_count: int = 2
  verify_with_stt: bool = True
  verify_buffer_seconds: float = 1.4
  verify_post_roll_seconds: float = 0.35
  verify_whisper_model: str = ""
  cooldown_seconds: float = 1.2


@dataclass(frozen=True)
class SttConfig:
  provider: str = "faster-whisper"
  whisper_model: str = "small.en"
  whisper_device: str = "cpu"
  whisper_compute_type: str = "int8"
  fallback_to_vosk: bool = True
  language: str = "en"


@dataclass(frozen=True)
class LlmConfig:
  provider: str = "ollama"
  endpoint: str = "http://127.0.0.1:11434"
  model: str = "gpt-oss:20b"
  timeout_seconds: float = 90.0
  temperature: float = 0.2
  max_tokens: int = 180
  fallback_dictionary: bool = True


@dataclass(frozen=True)
class WordConfig:
  command_words: tuple[str, ...] = (
    "add",
    "append",
    "save",
    "write",
    "word",
    "term",
    "vocabulary",
    "dictionary",
    "please",
    "the",
    "a",
    "an",
    "new",
  )
  ignored_words: tuple[str, ...] = (
    "and",
    "or",
    "but",
    "oh",
    "uh",
    "um",
    "ah",
    "eh",
    "hmm",
    "in",
    "on",
    "at",
    "of",
    "to",
    "for",
    "from",
    "with",
    "by",
    "into",
    "onto",
    "over",
    "under",
    "up",
    "down",
    "out",
    "off",
  )
  allow_hyphenated: bool = True
  max_candidates: int = 1
  singularize_simple_plurals: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
  log_level: str = "INFO"
  log_file: Path | None = Path("~/.local/state/obsidian-voice-vocab/daemon.log")


@dataclass(frozen=True)
class AppConfig:
  vault: VaultConfig = field(default_factory=VaultConfig)
  duplicates: DuplicateConfig = field(default_factory=DuplicateConfig)
  audio: AudioConfig = field(default_factory=AudioConfig)
  feedback: FeedbackConfig = field(default_factory=FeedbackConfig)
  wake: WakeConfig = field(default_factory=WakeConfig)
  stt: SttConfig = field(default_factory=SttConfig)
  llm: LlmConfig = field(default_factory=LlmConfig)
  words: WordConfig = field(default_factory=WordConfig)
  runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

  @classmethod
  def load(cls, path: Path | str | None) -> "AppConfig":
    if path is None:
      return cls().expanded()

    config_path = Path(path).expanduser()
    if not config_path.exists():
      raise FileNotFoundError(f"config file does not exist: {config_path}")

    with config_path.open("rb") as handle:
      raw = tomllib.load(handle)

    return cls(
      vault=VaultConfig(
        path=_path(raw, "vault", "path", default=VaultConfig.path),
        dictionary_folder=_string(raw, "vault", "dictionary_folder", default=VaultConfig.dictionary_folder),
        alphabet_files=tuple(_list(raw, "vault", "alphabet_files", default=list(VaultConfig.alphabet_files))),
      ),
      duplicates=DuplicateConfig(
        overwrite_existing=_bool(raw, "duplicates", "overwrite_existing", default=DuplicateConfig.overwrite_existing),
      ),
      audio=AudioConfig(
        sample_rate=_int(raw, "audio", "sample_rate", default=AudioConfig.sample_rate),
        device=_optional_device(raw.get("audio", {}).get("device", AudioConfig.device)),
        channels=_int(raw, "audio", "channels", default=AudioConfig.channels),
        block_ms=_int(raw, "audio", "block_ms", default=AudioConfig.block_ms),
        active_window_seconds=_float(raw, "audio", "active_window_seconds", default=AudioConfig.active_window_seconds),
        speech_start_timeout_seconds=_float(raw, "audio", "speech_start_timeout_seconds", default=AudioConfig.speech_start_timeout_seconds),
        speech_silence_stop_seconds=_float(raw, "audio", "speech_silence_stop_seconds", default=AudioConfig.speech_silence_stop_seconds),
        speech_min_seconds=_float(raw, "audio", "speech_min_seconds", default=AudioConfig.speech_min_seconds),
        speech_pre_roll_ms=_int(raw, "audio", "speech_pre_roll_ms", default=AudioConfig.speech_pre_roll_ms),
        speech_start_blocks=_int(raw, "audio", "speech_start_blocks", default=AudioConfig.speech_start_blocks),
        speech_rms_threshold=_float(raw, "audio", "speech_rms_threshold", default=AudioConfig.speech_rms_threshold),
        speech_peak_threshold=_float(raw, "audio", "speech_peak_threshold", default=AudioConfig.speech_peak_threshold),
        speech_finish_grace_seconds=_float(raw, "audio", "speech_finish_grace_seconds", default=AudioConfig.speech_finish_grace_seconds),
        vad_mode=_int(raw, "audio", "vad_mode", default=AudioConfig.vad_mode),
        vad_frame_ms=_int(raw, "audio", "vad_frame_ms", default=AudioConfig.vad_frame_ms),
      ),
      feedback=FeedbackConfig(
        hyprctl_notify=_bool(raw, "feedback", "hyprctl_notify", default=FeedbackConfig.hyprctl_notify),
        sound=_bool(raw, "feedback", "sound", default=FeedbackConfig.sound),
        notify_send=_bool(raw, "feedback", "notify_send", default=FeedbackConfig.notify_send),
        timeout_ms=_int(raw, "feedback", "timeout_ms", default=FeedbackConfig.timeout_ms),
        min_interval_seconds=_float(raw, "feedback", "min_interval_seconds", default=FeedbackConfig.min_interval_seconds),
        rejection_interval_seconds=_float(raw, "feedback", "rejection_interval_seconds", default=FeedbackConfig.rejection_interval_seconds),
        dedupe_window_seconds=_float(raw, "feedback", "dedupe_window_seconds", default=FeedbackConfig.dedupe_window_seconds),
        show_wake_rejections=_bool(raw, "feedback", "show_wake_rejections", default=FeedbackConfig.show_wake_rejections),
        ready_sound=_path(raw, "feedback", "ready_sound", default=FeedbackConfig.ready_sound),
        wake_sound=_path(raw, "feedback", "wake_sound", default=FeedbackConfig.wake_sound),
        success_sound=_path(raw, "feedback", "success_sound", default=FeedbackConfig.success_sound),
        error_sound=_path(raw, "feedback", "error_sound", default=FeedbackConfig.error_sound),
      ),
      wake=WakeConfig(
        phrase=_string(raw, "wake", "phrase", default=WakeConfig.phrase).lower(),
        phrase_variants=tuple(item.lower() for item in _list(raw, "wake", "phrase_variants", default=list(WakeConfig.phrase_variants))),
        provider=_string(raw, "wake", "provider", default=WakeConfig.provider),
        model_path=_path(raw, "wake", "model_path", default=WakeConfig.model_path),
        openwakeword_model_path=_path(raw, "wake", "openwakeword_model_path", default=WakeConfig.openwakeword_model_path),
        openwakeword_threshold=_float(raw, "wake", "openwakeword_threshold", default=WakeConfig.openwakeword_threshold),
        openwakeword_trigger_level=_int(raw, "wake", "openwakeword_trigger_level", default=WakeConfig.openwakeword_trigger_level),
        require_exact_match=_bool(raw, "wake", "require_exact_match", default=WakeConfig.require_exact_match),
        partial_confirmation_count=_int(raw, "wake", "partial_confirmation_count", default=WakeConfig.partial_confirmation_count),
        verify_with_stt=_bool(raw, "wake", "verify_with_stt", default=WakeConfig.verify_with_stt),
        verify_buffer_seconds=_float(raw, "wake", "verify_buffer_seconds", default=WakeConfig.verify_buffer_seconds),
        verify_post_roll_seconds=_float(raw, "wake", "verify_post_roll_seconds", default=WakeConfig.verify_post_roll_seconds),
        verify_whisper_model=_string(raw, "wake", "verify_whisper_model", default=WakeConfig.verify_whisper_model),
        cooldown_seconds=_float(raw, "wake", "cooldown_seconds", default=WakeConfig.cooldown_seconds),
      ),
      stt=SttConfig(
        provider=_string(raw, "stt", "provider", default=SttConfig.provider),
        whisper_model=_string(raw, "stt", "whisper_model", default=SttConfig.whisper_model),
        whisper_device=_string(raw, "stt", "whisper_device", default=SttConfig.whisper_device),
        whisper_compute_type=_string(raw, "stt", "whisper_compute_type", default=SttConfig.whisper_compute_type),
        fallback_to_vosk=_bool(raw, "stt", "fallback_to_vosk", default=SttConfig.fallback_to_vosk),
        language=_string(raw, "stt", "language", default=SttConfig.language),
      ),
      llm=LlmConfig(
        provider=_string(raw, "llm", "provider", default=LlmConfig.provider),
        endpoint=_string(raw, "llm", "endpoint", default=LlmConfig.endpoint).rstrip("/"),
        model=_string(raw, "llm", "model", default=LlmConfig.model),
        timeout_seconds=_float(raw, "llm", "timeout_seconds", default=LlmConfig.timeout_seconds),
        temperature=_float(raw, "llm", "temperature", default=LlmConfig.temperature),
        max_tokens=_int(raw, "llm", "max_tokens", default=LlmConfig.max_tokens),
        fallback_dictionary=_bool(raw, "llm", "fallback_dictionary", default=LlmConfig.fallback_dictionary),
      ),
      words=WordConfig(
        command_words=tuple(word.lower() for word in _list(raw, "words", "command_words", default=list(WordConfig.command_words))),
        ignored_words=tuple(word.lower() for word in _list(raw, "words", "ignored_words", default=list(WordConfig.ignored_words))),
        allow_hyphenated=_bool(raw, "words", "allow_hyphenated", default=WordConfig.allow_hyphenated),
        max_candidates=_int(raw, "words", "max_candidates", default=WordConfig.max_candidates),
        singularize_simple_plurals=_bool(raw, "words", "singularize_simple_plurals", default=WordConfig.singularize_simple_plurals),
      ),
      runtime=RuntimeConfig(
        log_level=_string(raw, "runtime", "log_level", default=RuntimeConfig.log_level),
        log_file=_optional_path(raw, "runtime", "log_file", default=RuntimeConfig.log_file),
      ),
    ).expanded()

  def expanded(self) -> "AppConfig":
    return AppConfig(
      vault=VaultConfig(
        path=_expand(self.vault.path),
        dictionary_folder=self.vault.dictionary_folder,
        alphabet_files=self.vault.alphabet_files,
      ),
      duplicates=self.duplicates,
      audio=self.audio,
      feedback=FeedbackConfig(
        hyprctl_notify=self.feedback.hyprctl_notify,
        sound=self.feedback.sound,
        notify_send=self.feedback.notify_send,
        timeout_ms=self.feedback.timeout_ms,
        min_interval_seconds=self.feedback.min_interval_seconds,
        rejection_interval_seconds=self.feedback.rejection_interval_seconds,
        dedupe_window_seconds=self.feedback.dedupe_window_seconds,
        show_wake_rejections=self.feedback.show_wake_rejections,
        ready_sound=_expand(self.feedback.ready_sound),
        wake_sound=_expand(self.feedback.wake_sound),
        success_sound=_expand(self.feedback.success_sound),
        error_sound=_expand(self.feedback.error_sound),
      ),
      wake=WakeConfig(
        phrase=self.wake.phrase.lower(),
        phrase_variants=tuple(item.lower() for item in self.wake.phrase_variants),
        provider=self.wake.provider,
        model_path=_expand(self.wake.model_path),
        require_exact_match=self.wake.require_exact_match,
        partial_confirmation_count=self.wake.partial_confirmation_count,
        verify_with_stt=self.wake.verify_with_stt,
        verify_buffer_seconds=self.wake.verify_buffer_seconds,
        verify_post_roll_seconds=self.wake.verify_post_roll_seconds,
        verify_whisper_model=self.wake.verify_whisper_model,
        cooldown_seconds=self.wake.cooldown_seconds,
      ),
      stt=self.stt,
      llm=self.llm,
      words=self.words,
      runtime=RuntimeConfig(
        log_level=self.runtime.log_level.upper(),
        log_file=_expand(self.runtime.log_file) if self.runtime.log_file else None,
      ),
    )

  @property
  def dictionary_path(self) -> Path:
    return self.vault.path / self.vault.dictionary_folder


def default_config_path() -> Path:
  return Path("~/.config/obsidian-voice-vocab/config.toml").expanduser()


def _expand(path: Path) -> Path:
  return Path(os.path.expandvars(str(path))).expanduser()


def _path(raw: dict[str, Any], section: str, key: str, default: Path) -> Path:
  return Path(str(raw.get(section, {}).get(key, default)))


def _optional_path(raw: dict[str, Any], section: str, key: str, default: Path | None) -> Path | None:
  value = raw.get(section, {}).get(key, default)
  if value in (None, ""):
    return None
  return Path(str(value))


def _string(raw: dict[str, Any], section: str, key: str, default: str) -> str:
  return str(raw.get(section, {}).get(key, default))


def _int(raw: dict[str, Any], section: str, key: str, default: int) -> int:
  return int(raw.get(section, {}).get(key, default))


def _float(raw: dict[str, Any], section: str, key: str, default: float) -> float:
  return float(raw.get(section, {}).get(key, default))


def _bool(raw: dict[str, Any], section: str, key: str, default: bool) -> bool:
  return bool(raw.get(section, {}).get(key, default))


def _list(raw: dict[str, Any], section: str, key: str, default: list[str]) -> list[str]:
  value = raw.get(section, {}).get(key, default)
  if not isinstance(value, list):
    raise ValueError(f"{section}.{key} must be a TOML array")
  return [str(item) for item in value]


def _optional_device(value: Any) -> str | int | None:
  if value in (None, ""):
    return None
  if isinstance(value, int):
    return value
  text = str(value)
  if text.isdigit():
    return int(text)
  return text
