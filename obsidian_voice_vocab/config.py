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
  block_ms: int = 80
  active_window_seconds: float = 6.0


@dataclass(frozen=True)
class WakeConfig:
  phrase: str = "hello obsidian"
  provider: str = "vosk-grammar"
  model_path: Path = Path("~/.local/share/obsidian-voice-vocab/models/vosk-model-small-en-us-0.15")


@dataclass(frozen=True)
class SttConfig:
  provider: str = "faster-whisper"
  whisper_model: str = "base.en"
  whisper_device: str = "auto"
  whisper_compute_type: str = "int8"
  fallback_to_vosk: bool = True
  language: str = "en"


@dataclass(frozen=True)
class LlmConfig:
  provider: str = "ollama"
  endpoint: str = "http://127.0.0.1:11434"
  model: str = "qwen2.5:1.5b"
  timeout_seconds: float = 20.0
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
  allow_hyphenated: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
  log_level: str = "INFO"
  log_file: Path | None = Path("~/.local/state/obsidian-voice-vocab/daemon.log")


@dataclass(frozen=True)
class AppConfig:
  vault: VaultConfig = field(default_factory=VaultConfig)
  duplicates: DuplicateConfig = field(default_factory=DuplicateConfig)
  audio: AudioConfig = field(default_factory=AudioConfig)
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
      ),
      wake=WakeConfig(
        phrase=_string(raw, "wake", "phrase", default=WakeConfig.phrase).lower(),
        provider=_string(raw, "wake", "provider", default=WakeConfig.provider),
        model_path=_path(raw, "wake", "model_path", default=WakeConfig.model_path),
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
        allow_hyphenated=_bool(raw, "words", "allow_hyphenated", default=WordConfig.allow_hyphenated),
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
      wake=WakeConfig(
        phrase=self.wake.phrase.lower(),
        provider=self.wake.provider,
        model_path=_expand(self.wake.model_path),
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

