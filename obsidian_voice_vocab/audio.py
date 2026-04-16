from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
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


class AudioRecorder:
  def __init__(self, config: AppConfig):
    self.config = config

  def record_wav(self, seconds: float) -> Path:
    sd = _sounddevice()
    chunks: list[bytes] = []
    sample_rate = self.config.audio.sample_rate
    channels = self.config.audio.channels
    blocksize = max(1, int(sample_rate * self.config.audio.block_ms / 1000))

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during active recording: %s", status)
      chunks.append(bytes(indata))

    LOG.info("active recording started window=%.1fs sample_rate=%s device=%s", seconds, sample_rate, self.config.audio.device)
    try:
      with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=blocksize,
        dtype="int16",
        channels=channels,
        device=self.config.audio.device,
        callback=callback,
      ):
        time.sleep(seconds)
    except Exception as exc:
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
    LOG.info("active recording saved path=%s bytes=%s", path, path.stat().st_size)
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
          values = memoryview(data).cast("h")
          for value in values:
            peak = max(peak, abs(int(value)))
            square_sum += float(value) * float(value)
          samples += len(values)
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
