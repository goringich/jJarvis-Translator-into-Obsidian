from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from collections import deque
from dataclasses import dataclass
import json
import logging
import math
import queue
import time
import wave

from .config import AppConfig


LOG = logging.getLogger(__name__)


class AudioError(RuntimeError):
  pass


@dataclass(frozen=True)
class AudioLevel:
  rms: float
  peak: float
  samples: int


class AudioRecorder:
  def __init__(self, config: AppConfig):
    self.config = config

  def record_wav(self, seconds: float) -> Path:
    sd = _sounddevice()
    chunks: list[bytes] = []
    pre_roll: deque[bytes] = deque()
    sample_rate = self.config.audio.sample_rate
    channels = self.config.audio.channels
    blocksize = max(1, int(sample_rate * self.config.audio.block_ms / 1000))
    block_seconds = blocksize / sample_rate
    pre_roll_blocks = max(1, int(self.config.audio.speech_pre_roll_ms / self.config.audio.block_ms))
    max_seconds = max(seconds, self.config.audio.speech_min_seconds)
    speech_start_timeout = min(self.config.audio.speech_start_timeout_seconds, max_seconds)
    silence_stop = self.config.audio.speech_silence_stop_seconds
    speech_min = self.config.audio.speech_min_seconds
    speech_started_at: float | None = None
    last_speech_at: float | None = None
    speech_streak = 0
    max_rms = 0.0
    max_peak = 0.0
    callback_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during active recording: %s", status)
      callback_queue.put(bytes(indata))

    LOG.info(
      "active speech recording armed max_window=%.1fs start_timeout=%.1fs silence_stop=%.1fs start_blocks=%s rms_threshold=%.4f peak_threshold=%.4f sample_rate=%s device=%s",
      max_seconds,
      speech_start_timeout,
      silence_stop,
      self.config.audio.speech_start_blocks,
      self.config.audio.speech_rms_threshold,
      self.config.audio.speech_peak_threshold,
      sample_rate,
      self.config.audio.device,
    )
    try:
      with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=blocksize,
        dtype="int16",
        channels=channels,
        device=self.config.audio.device,
        callback=callback,
      ):
        started = time.monotonic()
        while True:
          now = time.monotonic()
          elapsed = now - started
          if elapsed >= max_seconds:
            break
          try:
            data = callback_queue.get(timeout=max(0.1, min(block_seconds, max_seconds - elapsed)))
          except queue.Empty:
            continue
          level = _level_for_chunk(data)
          max_rms = max(max_rms, level.rms)
          max_peak = max(max_peak, level.peak)
          is_speech = level.rms >= self.config.audio.speech_rms_threshold or level.peak >= self.config.audio.speech_peak_threshold

          if speech_started_at is None:
            pre_roll.append(data)
            while len(pre_roll) > pre_roll_blocks:
              pre_roll.popleft()
            if is_speech:
              speech_streak += 1
              if speech_streak >= max(1, self.config.audio.speech_start_blocks):
                speech_started_at = elapsed - ((speech_streak - 1) * block_seconds)
                last_speech_at = elapsed
                chunks.extend(pre_roll)
                pre_roll.clear()
                LOG.info("speech start detected at=%.2fs rms=%.4f peak=%.4f streak=%s", speech_started_at, level.rms, level.peak, speech_streak)
            else:
              speech_streak = 0
            if speech_started_at is None and elapsed >= speech_start_timeout:
              raise AudioError(
                "no speech detected after wake phrase "
                f"(timeout={speech_start_timeout:.1f}s max_rms={max_rms:.4f} max_peak={max_peak:.4f})"
              )
            continue

          chunks.append(data)
          if is_speech:
            last_speech_at = elapsed
          speech_duration = elapsed - speech_started_at
          silence_duration = elapsed - (last_speech_at or elapsed)
          if speech_duration >= speech_min and silence_duration >= silence_stop:
            LOG.info("speech end detected at=%.2fs speech_duration=%.2fs silence=%.2fs", elapsed, speech_duration, silence_duration)
            break
    except Exception as exc:
      if isinstance(exc, AudioError):
        raise
      raise AudioError(f"failed to record microphone audio: {exc}") from exc

    if not chunks:
      raise AudioError("microphone produced no audio chunks")

    with NamedTemporaryFile("wb", suffix=".wav", delete=False) as tmp:
      path = Path(tmp.name)
    with wave.open(str(path), "wb") as handle:
      handle.setnchannels(channels)
      handle.setsampwidth(2)
      handle.setframerate(sample_rate)
      handle.writeframes(b"".join(chunks))
    LOG.info("active recording saved path=%s bytes=%s max_rms=%.4f max_peak=%.4f", path, path.stat().st_size, max_rms, max_peak)
    return path

  def measure_level(self, seconds: float) -> tuple[float, float, int]:
    sd = _sounddevice()
    audio_queue: queue.Queue[bytes] = queue.Queue()
    sample_rate = self.config.audio.sample_rate
    channels = self.config.audio.channels
    blocksize = max(1, int(sample_rate * self.config.audio.block_ms / 1000))

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during level test: %s", status)
      audio_queue.put(bytes(indata))

    samples = 0
    square_sum = 0.0
    peak = 0
    started = time.monotonic()
    try:
      with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=blocksize,
        dtype="int16",
        channels=channels,
        device=self.config.audio.device,
        callback=callback,
      ):
        while time.monotonic() - started < seconds:
          data = audio_queue.get(timeout=max(0.1, seconds))
          level = _raw_level_for_chunk(data)
          peak = max(peak, level.peak)
          square_sum += level.rms * level.rms * level.samples
          samples += level.samples
    except Exception as exc:
      raise AudioError(f"failed to measure microphone audio: {exc}") from exc

    if samples == 0:
      raise AudioError("microphone produced no samples during level test")
    rms = math.sqrt(square_sum / samples)
    return rms / 32768.0, peak / 32768.0, samples


class WakeWordListener:
  def __init__(self, config: AppConfig):
    self.config = config
    self.phrase = _normalize_phrase(config.wake.phrase)
    self.phrases = tuple(dict.fromkeys(_normalize_phrase(item) for item in config.wake.phrase_variants + (config.wake.phrase,)))
    if config.wake.provider != "vosk-grammar":
      raise AudioError(f"unsupported wake.provider: {config.wake.provider}")

  def wait(self) -> str:
    sd = _sounddevice()
    vosk = _vosk()
    model_path = self.config.wake.model_path
    if not model_path.exists():
      raise AudioError(f"Vosk wake model path does not exist: {model_path}")

    model = vosk.Model(str(model_path))
    grammar = json.dumps([*self.phrases, "[unk]"])
    recognizer = vosk.KaldiRecognizer(model, self.config.audio.sample_rate, grammar)
    audio_queue: queue.Queue[bytes] = queue.Queue()
    blocksize = max(1, int(self.config.audio.sample_rate * self.config.audio.block_ms / 1000))

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during wake listening: %s", status)
      audio_queue.put(bytes(indata))

    LOG.info("waiting for wake phrases=%s provider=vosk-grammar device=%s", self.phrases, self.config.audio.device)
    try:
      with sd.RawInputStream(
        samplerate=self.config.audio.sample_rate,
        blocksize=blocksize,
        dtype="int16",
        channels=self.config.audio.channels,
        device=self.config.audio.device,
        callback=callback,
      ):
        while True:
          data = audio_queue.get()
          if recognizer.AcceptWaveform(data):
            text = _extract_vosk_text(recognizer.Result())
            if self._contains_wake_phrase(text):
              LOG.info("wake phrase detected text=%r", text)
              return text
          else:
            partial = _extract_vosk_partial(recognizer.PartialResult())
            if self._contains_wake_phrase(partial):
              LOG.info("wake phrase detected partial=%r", partial)
              recognizer.Reset()
              return partial
    except KeyboardInterrupt:
      raise
    except Exception as exc:
      raise AudioError(f"wake listener failed: {exc}") from exc

  def _contains_wake_phrase(self, text: str) -> bool:
    normalized = _normalize_phrase(text)
    return any(phrase in normalized for phrase in self.phrases)


class SpeechTranscriber:
  def __init__(self, config: AppConfig):
    self.config = config
    self._whisper_model = None
    self._vosk_model = None

  def transcribe(self, wav_path: Path) -> str:
    provider = self.config.stt.provider.lower()
    if provider == "faster-whisper":
      try:
        return self._transcribe_whisper(wav_path)
      except Exception as exc:
        if not self.config.stt.fallback_to_vosk:
          raise
        LOG.warning("faster-whisper failed, falling back to Vosk: %s", exc)
        return self._transcribe_vosk(wav_path)
    if provider == "vosk":
      return self._transcribe_vosk(wav_path)
    raise AudioError(f"unsupported stt.provider: {self.config.stt.provider}")

  def _transcribe_whisper(self, wav_path: Path) -> str:
    faster_whisper = _faster_whisper()
    if self._whisper_model is None:
      LOG.info(
        "loading faster-whisper model=%s device=%s compute_type=%s",
        self.config.stt.whisper_model,
        self.config.stt.whisper_device,
        self.config.stt.whisper_compute_type,
      )
      self._whisper_model = faster_whisper.WhisperModel(
        self.config.stt.whisper_model,
        device=self.config.stt.whisper_device,
        compute_type=self.config.stt.whisper_compute_type,
      )
    segments, info = self._whisper_model.transcribe(
      str(wav_path),
      language=self.config.stt.language,
      beam_size=3,
      vad_filter=True,
      condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    LOG.info("faster-whisper recognized language=%s probability=%.3f text=%r", info.language, info.language_probability, text)
    return text

  def _transcribe_vosk(self, wav_path: Path) -> str:
    vosk = _vosk()
    model_path = self.config.wake.model_path
    if not model_path.exists():
      raise AudioError(f"Vosk model path does not exist for STT fallback: {model_path}")
    if self._vosk_model is None:
      self._vosk_model = vosk.Model(str(model_path))
    with wave.open(str(wav_path), "rb") as handle:
      if handle.getnchannels() != 1:
        raise AudioError("Vosk fallback expects mono WAV input")
      recognizer = vosk.KaldiRecognizer(self._vosk_model, handle.getframerate())
      while True:
        data = handle.readframes(4000)
        if not data:
          break
        recognizer.AcceptWaveform(data)
      text = _extract_vosk_text(recognizer.FinalResult())
    LOG.info("Vosk fallback recognized text=%r", text)
    return text


def list_audio_devices() -> str:
  sd = _sounddevice()
  return str(sd.query_devices())


def _raw_level_for_chunk(data: bytes) -> AudioLevel:
  values = memoryview(data).cast("h")
  samples = len(values)
  if samples == 0:
    return AudioLevel(rms=0.0, peak=0.0, samples=0)
  peak = 0
  square_sum = 0.0
  for value in values:
    integer = int(value)
    peak = max(peak, abs(integer))
    square_sum += float(integer) * float(integer)
  return AudioLevel(rms=math.sqrt(square_sum / samples), peak=float(peak), samples=samples)


def _level_for_chunk(data: bytes) -> AudioLevel:
  raw = _raw_level_for_chunk(data)
  return AudioLevel(rms=raw.rms / 32768.0, peak=raw.peak / 32768.0, samples=raw.samples)


def _sounddevice():
  try:
    import sounddevice as sd
  except Exception as exc:
    raise AudioError("Python package sounddevice is not installed or PortAudio is unavailable") from exc
  return sd


def _vosk():
  try:
    import vosk
  except Exception as exc:
    raise AudioError("Python package vosk is not installed") from exc
  vosk.SetLogLevel(-1)
  return vosk


def _faster_whisper():
  try:
    import faster_whisper
  except Exception as exc:
    raise AudioError("Python package faster-whisper is not installed") from exc
  return faster_whisper


def _extract_vosk_text(result: str) -> str:
  try:
    return str(json.loads(result).get("text", "")).strip()
  except json.JSONDecodeError:
    return ""


def _extract_vosk_partial(result: str) -> str:
  try:
    return str(json.loads(result).get("partial", "")).strip()
  except json.JSONDecodeError:
    return ""


def _contains_phrase(text: str, phrase: str) -> bool:
  return _normalize_phrase(phrase) in _normalize_phrase(text)


def _normalize_phrase(text: str) -> str:
  return " ".join(str(text or "").lower().replace("-", " ").split())
