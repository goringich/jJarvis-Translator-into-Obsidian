from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import logging
import math
import queue
import re
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


@dataclass(frozen=True)
class WakeDetection:
  text: str
  wav_path: Path
  via_partial: bool


class AudioRecorder:
  def __init__(self, config: AppConfig):
    self.config = config

  def record_wav(self, seconds: float) -> Path:
    sd = _sounddevice()
    chunks: list[bytes] = []
    sample_rate = self.config.audio.sample_rate
    channels = self.config.audio.channels
    vad = _webrtcvad(self.config.audio.vad_mode)
    frame_ms = self.config.audio.vad_frame_ms
    frame_samples = max(1, int(sample_rate * frame_ms / 1000))
    blocksize = frame_samples
    frame_seconds = frame_samples / sample_rate
    max_seconds = max(seconds, self.config.audio.speech_min_seconds)
    silence_stop = self.config.audio.speech_silence_stop_seconds
    speech_min = self.config.audio.speech_min_seconds
    finish_grace = self.config.audio.speech_finish_grace_seconds
    pre_roll_frames = max(1, int(self.config.audio.speech_pre_roll_ms / frame_ms))
    last_voiced_elapsed: float | None = None
    first_voiced_index: int | None = None
    last_voiced_index: int | None = None
    max_rms = 0.0
    max_peak = 0.0
    callback_queue: queue.Queue[bytes] = queue.Queue()

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during active recording: %s", status)
      callback_queue.put(bytes(indata))

    LOG.info(
      "active speech recording started immediately max_window=%.1fs silence_stop=%.1fs finish_grace=%.2fs vad_mode=%s frame_ms=%s sample_rate=%s device=%s",
      max_seconds,
      silence_stop,
      finish_grace,
      self.config.audio.vad_mode,
      frame_ms,
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
            data = callback_queue.get(timeout=max(0.1, min(frame_seconds, max_seconds - elapsed)))
          except queue.Empty:
            continue
          level = _level_for_chunk(data)
          max_rms = max(max_rms, level.rms)
          max_peak = max(max_peak, level.peak)
          is_voiced = (
            vad.is_speech(data, sample_rate)
            and (
              level.rms >= self.config.audio.speech_rms_threshold
              or level.peak >= self.config.audio.speech_peak_threshold
            )
          )
          chunks.append(data)
          index = len(chunks) - 1
          if is_voiced:
            if first_voiced_index is None:
              first_voiced_index = index
              LOG.info("first voiced frame detected at=%.2fs rms=%.4f peak=%.4f", elapsed, level.rms, level.peak)
            last_voiced_index = index
            last_voiced_elapsed = elapsed
          speech_duration = ((last_voiced_index - first_voiced_index + 1) * frame_seconds) if first_voiced_index is not None and last_voiced_index is not None else 0.0
          silence_duration = elapsed - (last_voiced_elapsed if last_voiced_elapsed is not None else elapsed)
          if last_voiced_elapsed is not None and speech_duration >= speech_min and silence_duration >= silence_stop:
            LOG.info("speech end detected at=%.2fs speech_duration=%.2fs silence=%.2fs", elapsed, speech_duration, silence_duration)
            break
    except Exception as exc:
      if isinstance(exc, AudioError):
        raise
      raise AudioError(f"failed to record microphone audio: {exc}") from exc

    if not chunks:
      raise AudioError("microphone produced no audio chunks")
    if last_voiced_index is None or first_voiced_index is None:
      raise AudioError(
        "no voiced speech detected in active recording "
        f"(max_rms={max_rms:.4f} max_peak={max_peak:.4f})"
      )

    start_index = max(0, first_voiced_index - pre_roll_frames)
    grace_frames = max(1, int(math.ceil(finish_grace / frame_seconds)))
    end_index = min(len(chunks), last_voiced_index + grace_frames + 1)
    trimmed_chunks = chunks[start_index:end_index]
    trim_seconds = len(trimmed_chunks) * frame_seconds

    with NamedTemporaryFile("wb", suffix=".wav", delete=False) as tmp:
      path = Path(tmp.name)
    _write_wav(path, b"".join(trimmed_chunks), sample_rate, channels)
    LOG.info(
      "active recording saved path=%s bytes=%s max_rms=%.4f max_peak=%.4f last_speech=%.2fs trim_seconds=%.2fs",
      path,
      path.stat().st_size,
      max_rms,
      max_peak,
      last_voiced_elapsed,
      trim_seconds,
    )
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
    self.confirmation_count = max(1, config.wake.partial_confirmation_count)
    if config.wake.provider != "vosk-grammar":
      raise AudioError(f"unsupported wake.provider: {config.wake.provider}")

  def wait(self) -> WakeDetection:
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
    block_seconds = blocksize / self.config.audio.sample_rate
    buffer_frames = max(1, int(self.config.wake.verify_buffer_seconds / block_seconds))
    post_roll_frames = max(1, int(self.config.wake.verify_post_roll_seconds / block_seconds))
    recent_frames: deque[bytes] = deque(maxlen=buffer_frames)
    consecutive_partial_matches = 0
    last_partial = ""
    last_detection_at = 0.0

    def callback(indata, frames, time_info, status) -> None:
      if status:
        LOG.warning("audio input status during wake listening: %s", status)
      data = bytes(indata)
      audio_queue.put(data)

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
          recent_frames.append(data)
          if recognizer.AcceptWaveform(data):
            text = _extract_vosk_text(recognizer.Result())
            if self._contains_wake_phrase(text):
              if time.monotonic() - last_detection_at < self.config.wake.cooldown_seconds:
                LOG.info("wake candidate ignored by cooldown text=%r", text)
                recognizer.Reset()
                continue
              wav_path = self._capture_detection_clip(audio_queue, recent_frames, post_roll_frames)
              last_detection_at = time.monotonic()
              LOG.info("wake phrase detected text=%r wav=%s", text, wav_path)
              return WakeDetection(text=text, wav_path=wav_path, via_partial=False)
            consecutive_partial_matches = 0
            last_partial = ""
          else:
            partial = _extract_vosk_partial(recognizer.PartialResult())
            if self._contains_wake_phrase(partial):
              if partial == last_partial:
                consecutive_partial_matches += 1
              else:
                consecutive_partial_matches = 1
                last_partial = partial
              if consecutive_partial_matches >= self.confirmation_count:
                if time.monotonic() - last_detection_at < self.config.wake.cooldown_seconds:
                  LOG.info("wake partial ignored by cooldown partial=%r", partial)
                  recognizer.Reset()
                  continue
                wav_path = self._capture_detection_clip(audio_queue, recent_frames, post_roll_frames)
                last_detection_at = time.monotonic()
                LOG.info("wake phrase detected partial=%r confirmations=%s wav=%s", partial, consecutive_partial_matches, wav_path)
                recognizer.Reset()
                return WakeDetection(text=partial, wav_path=wav_path, via_partial=True)
            else:
              consecutive_partial_matches = 0
              last_partial = ""
    except KeyboardInterrupt:
      raise
    except Exception as exc:
      raise AudioError(f"wake listener failed: {exc}") from exc

  def _contains_wake_phrase(self, text: str) -> bool:
    normalized = _normalize_phrase(text)
    if self.config.wake.require_exact_match:
      return normalized in self.phrases
    return any(normalized.endswith(phrase) or phrase in normalized for phrase in self.phrases)

  def _capture_detection_clip(
    self,
    audio_queue: queue.Queue[bytes],
    recent_frames: deque[bytes],
    post_roll_frames: int,
  ) -> Path:
    frames = list(recent_frames)
    deadline = time.monotonic() + max(0.2, self.config.wake.verify_post_roll_seconds + 0.1)
    while post_roll_frames > 0 and time.monotonic() < deadline:
      timeout = max(0.05, deadline - time.monotonic())
      try:
        frame = audio_queue.get(timeout=timeout)
      except queue.Empty:
        break
      frames.append(frame)
      recent_frames.append(frame)
      post_roll_frames -= 1
    if not frames:
      raise AudioError("wake phrase clip capture produced no audio")
    with NamedTemporaryFile("wb", suffix=".wav", delete=False) as tmp:
      path = Path(tmp.name)
    _write_wav(path, b"".join(frames), self.config.audio.sample_rate, self.config.audio.channels)
    return path


class SpeechTranscriber:
  def __init__(self, config: AppConfig):
    self.config = config
    self._whisper_models: dict[str, object] = {}
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
    primary = self._transcribe_whisper_with_options(
      wav_path,
      model_name=self.config.stt.whisper_model,
      prompt="One spoken English vocabulary word. Prefer a single word over a sentence.",
      beam_size=5,
      best_of=5,
      vad_filter=True,
    )
    if 0 < len(primary.split()) <= 3:
      return primary
    focused = self._transcribe_whisper_with_options(
      wav_path,
      model_name=self.config.stt.whisper_model,
      prompt="Single English word.",
      beam_size=6,
      best_of=6,
      vad_filter=False,
    )
    if focused and (not primary or len(focused.split()) < len(primary.split())):
      LOG.info("using focused whisper transcript primary=%r focused=%r", primary, focused)
      return focused
    return primary

  def verify_wake_phrase(self, wav_path: Path, phrases: tuple[str, ...]) -> tuple[bool, str]:
    model_name = self.config.wake.verify_whisper_model or self.config.stt.whisper_model
    prompt = _build_wake_verification_prompt(phrases)
    best_text = ""
    best_score = 0.0
    for vad_filter, beam_size, best_of in ((True, 1, 1), (False, 2, 2)):
      text = self._transcribe_whisper_with_options(
        wav_path,
        model_name=model_name,
        prompt=prompt,
        beam_size=beam_size,
        best_of=best_of,
        vad_filter=vad_filter,
      )
      normalized = _normalize_phrase(text)
      score = max((_wake_phrase_score(normalized, phrase) for phrase in phrases), default=0.0)
      if score > best_score:
        best_score = score
        best_text = text
      matched = any(_wake_phrase_matches(normalized, phrase) for phrase in phrases)
      LOG.info(
        "wake verification attempt model=%s vad_filter=%s text=%r score=%.3f matched=%s",
        model_name,
        vad_filter,
        text,
        score,
        matched,
      )
      if matched:
        return True, text
    return False, best_text

  def _transcribe_whisper_with_options(
    self,
    wav_path: Path,
    model_name: str,
    prompt: str | None,
    beam_size: int,
    best_of: int,
    vad_filter: bool,
  ) -> str:
    faster_whisper = _faster_whisper()
    whisper_model = self._whisper_models.get(model_name)
    if whisper_model is None:
      LOG.info(
        "loading faster-whisper model=%s device=%s compute_type=%s",
        model_name,
        self.config.stt.whisper_device,
        self.config.stt.whisper_compute_type,
      )
      whisper_model = faster_whisper.WhisperModel(
        model_name,
        device=self.config.stt.whisper_device,
        compute_type=self.config.stt.whisper_compute_type,
      )
      self._whisper_models[model_name] = whisper_model
    segments, info = whisper_model.transcribe(
      str(wav_path),
      language=self.config.stt.language,
      initial_prompt=prompt or None,
      beam_size=beam_size,
      best_of=best_of,
      vad_filter=vad_filter,
      condition_on_previous_text=False,
      temperature=0.0,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    LOG.info(
      "faster-whisper recognized model=%s language=%s probability=%.3f vad_filter=%s text=%r",
      model_name,
      info.language,
      info.language_probability,
      vad_filter,
      text,
    )
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


def _webrtcvad(mode: int):
  try:
    import _webrtcvad
  except Exception as exc:
    raise AudioError("Python package webrtcvad is not installed") from exc
  return _VadWrapper(_webrtcvad, max(0, min(3, int(mode))))


class _VadWrapper:
  def __init__(self, backend, mode: int):
    self._backend = backend
    self._vad = backend.create()
    backend.init(self._vad)
    backend.set_mode(self._vad, mode)

  def is_speech(self, buf: bytes, sample_rate: int) -> bool:
    length = int(len(buf) / 2)
    return bool(self._backend.process(self._vad, sample_rate, buf, length))


def _write_wav(path: Path, audio_bytes: bytes, sample_rate: int, channels: int) -> None:
  with wave.open(str(path), "wb") as handle:
    handle.setnchannels(channels)
    handle.setsampwidth(2)
    handle.setframerate(sample_rate)
    handle.writeframes(audio_bytes)


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
  cleaned = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower().replace("-", " "))
  return " ".join(cleaned.split())


def _wake_phrase_matches(normalized_text: str, normalized_phrase: str) -> bool:
  return _wake_phrase_score(normalized_text, normalized_phrase) >= 0.84


def _wake_phrase_score(normalized_text: str, normalized_phrase: str) -> float:
  if not normalized_text or not normalized_phrase:
    return 0.0
  if (
    normalized_text == normalized_phrase
    or normalized_text.startswith(normalized_phrase)
    or normalized_text.endswith(normalized_phrase)
    or normalized_phrase in normalized_text
  ):
    return 1.0

  phrase_words = normalized_phrase.split()
  text_words = normalized_text.split()
  if not phrase_words or not text_words:
    return 0.0

  window_size = len(phrase_words)
  if len(text_words) < window_size:
    windows = [normalized_text]
  else:
    windows = [" ".join(text_words[index:index + window_size]) for index in range(len(text_words) - window_size + 1)]

  best = 0.0
  for window in windows:
    overall = SequenceMatcher(None, window, normalized_phrase).ratio()
    if overall > best:
      best = overall
    window_words = window.split()
    if len(window_words) != window_size:
      continue
    token_scores = [_wake_token_score(left, right) for left, right in zip(window_words, phrase_words)]
    token_average = sum(token_scores) / len(token_scores)
    if token_average > best:
      best = token_average
  return best


def _wake_token_score(left: str, right: str) -> float:
  if left == right:
    return 1.0
  if left.startswith(right) or right.startswith(left):
    return 0.94
  return SequenceMatcher(None, left, right).ratio()


def _build_wake_verification_prompt(phrases: tuple[str, ...]) -> str:
  joined = ", ".join(dict.fromkeys(phrases))
  return (
    "Possible wake phrases: "
    f"{joined}. "
    "Prefer those exact words if they are present in the audio."
  )
