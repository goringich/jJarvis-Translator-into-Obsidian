from __future__ import annotations

import logging
import os
import queue
import threading
import time

from .audio import AudioRecorder, SpeechTranscriber, WakeWordListener
from .config import AppConfig
from .feedback import Feedback
from .llm import GeneratedEntry, build_adapter, fallback_for_word, generate_with_fallback
from .markdown_store import DictionaryStore, VocabEntry, read_entries
from .normalizer import WordExtractionError, extract_word


LOG = logging.getLogger(__name__)


class VoiceVocabularyDaemon:
  def __init__(self, config: AppConfig):
    self.config = config
    self.store = DictionaryStore(config)
    self.recorder = AudioRecorder(config)
    self.listener = WakeWordListener(config)
    self.transcriber = SpeechTranscriber(config)
    self.llm_adapter = build_adapter(config.llm)
    self.feedback = Feedback(config)
    self._enrich_queue: queue.Queue[str] = queue.Queue()
    self._enrich_pending: set[str] = set()
    self._enrich_lock = threading.Lock()
    if self._llm_background_enabled():
      self._enrich_thread = threading.Thread(
        target=self._enrichment_loop,
        name="obsidian-voice-vocab-enrich",
        daemon=True,
      )
      self._enrich_thread.start()
    else:
      self._enrich_thread = None

  def run(self, once: bool = False) -> None:
    self.store.initialize()
    LOG.info("service started pid=%s vault=%s dictionary=%s", os.getpid(), self.config.vault.path, self.config.dictionary_path)
    self.feedback.ready()
    consecutive_errors = 0
    while True:
      try:
        detection = self.listener.wait()
        consecutive_errors = 0
        if not self._verify_wake(detection):
          continue
        self.feedback.wake()
        self._handle_activation()
      except KeyboardInterrupt:
        LOG.info("service stopped by keyboard interrupt")
        return
      except Exception as exc:
        consecutive_errors += 1
        LOG.exception("daemon loop error: %s", exc)
        self.feedback.error(_short_reason(str(exc)))
      if once:
        LOG.info("single activation mode completed")
        return
      if consecutive_errors:
        backoff_seconds = min(30.0, 2.0 * consecutive_errors)
        LOG.warning("daemon loop backing off for %.1fs after %s consecutive error(s)", backoff_seconds, consecutive_errors)
        time.sleep(backoff_seconds)

  def _verify_wake(self, detection) -> bool:
    if not self.config.wake.verify_with_stt:
      try:
        detection.wav_path.unlink(missing_ok=True)
      except OSError as exc:
        LOG.warning("failed to delete wake clip %s: %s", detection.wav_path, exc)
      return True
    try:
      matched, verified_text = self.transcriber.verify_wake_phrase(detection.wav_path, self.listener.phrases)
      if matched:
        LOG.info(
          "wake verification accepted source=%r verified=%r via_partial=%s wav=%s",
          detection.text,
          verified_text,
          detection.via_partial,
          detection.wav_path,
        )
        return True
      LOG.warning(
        "wake verification rejected source=%r verified=%r via_partial=%s wav=%s",
        detection.text,
        verified_text,
        detection.via_partial,
        detection.wav_path,
      )
      self.feedback.wake_rejected(_short_reason(verified_text or "phrase mismatch"))
      return False
    finally:
      try:
        detection.wav_path.unlink(missing_ok=True)
      except OSError as exc:
        LOG.warning("failed to delete wake clip %s: %s", detection.wav_path, exc)

  def _handle_activation(self) -> None:
    wav_path = self.recorder.record_wav(self.config.audio.active_window_seconds)
    try:
      transcript = self.transcriber.transcribe(wav_path)
      extraction = extract_word(
        transcript,
        command_words=active_command_words(self.config),
        allow_hyphenated=self.config.words.allow_hyphenated,
        singularize_simple_plurals=self.config.words.singularize_simple_plurals,
      )
      unique_candidates = tuple(dict.fromkeys(extraction.candidates))
      if len(unique_candidates) > self.config.words.max_candidates:
        raise WordExtractionError(
          "recognized too many possible words; say one English word after the wake sound "
          f"(candidates={', '.join(unique_candidates)})"
        )
      if len(extraction.candidates) > len(unique_candidates):
        LOG.info("recognized repeated word candidates=%s unique=%s source=%r", extraction.candidates, unique_candidates, extraction.source_text)
      if len(unique_candidates) > 1:
        LOG.warning("multiple English word candidates recognized candidates=%s ignored=%s source=%r", unique_candidates, extraction.ignored_command_words, extraction.source_text)
      else:
        LOG.info("recognized word=%s source=%r", extraction.word, extraction.source_text)

      result = self._write_word_fast(extraction.word)
      LOG.info(
        "dictionary write complete word=%s letter=%s path=%s created=%s updated=%s total=%s",
        result.word,
        result.letter,
        result.path,
        result.created,
        result.updated,
        result.count,
      )
      self.feedback.success(result.word)
    except WordExtractionError as exc:
      LOG.warning("recognized speech rejected: %s", exc)
      self.feedback.rejected(_short_reason(str(exc)))
    finally:
      try:
        wav_path.unlink(missing_ok=True)
      except OSError as exc:
        LOG.warning("failed to delete temporary audio file %s: %s", wav_path, exc)

  def _write_word_fast(self, word: str):
    fast_entry = self._build_fast_entry(word)
    result = self.store.add_or_update(fast_entry)
    self._enqueue_enrichment_if_needed(word)
    return result

  def _build_fast_entry(self, word: str) -> VocabEntry:
    generated = self._fast_generated_entry(word)
    LOG.info(
      "fast entry word=%s translation=%r example=%r status=%s",
      word,
      generated.translation,
      generated.example,
      generated.status,
    )
    return VocabEntry(
      word=word,
      translation=generated.translation,
      example=generated.example,
      status=generated.status,
    )

  def _fast_generated_entry(self, word: str) -> GeneratedEntry:
    if self.config.llm.fallback_dictionary:
      return fallback_for_word(word, "queued")
    return GeneratedEntry(translation="", example="", status="queued")

  def _llm_background_enabled(self) -> bool:
    provider = self.config.llm.provider.lower().replace("_", "-")
    return provider not in ("none", "disabled", "off")

  def _enqueue_enrichment_if_needed(self, word: str) -> None:
    if not self._llm_background_enabled():
      return
    existing = self._existing_entry(word)
    if existing and existing.translation and existing.example and existing.status not in ("queued", "llm-failed"):
      LOG.info("background enrichment skipped word=%s reason=already-complete status=%s", word, existing.status)
      return
    with self._enrich_lock:
      if word in self._enrich_pending:
        LOG.info("background enrichment skipped word=%s reason=already-pending", word)
        return
      self._enrich_pending.add(word)
    self._enrich_queue.put(word)
    LOG.info("background enrichment queued word=%s", word)

  def _enrichment_loop(self) -> None:
    while True:
      word = self._enrich_queue.get()
      try:
        self._enrich_word(word)
      except Exception as exc:
        LOG.exception("background enrichment failed word=%s error=%s", word, exc)
      finally:
        with self._enrich_lock:
          self._enrich_pending.discard(word)
        self._enrich_queue.task_done()

  def _enrich_word(self, word: str) -> None:
    existing = self._existing_entry(word)
    if existing and existing.translation and existing.example and existing.status not in ("queued", "llm-failed"):
      LOG.info("background enrichment skipped word=%s reason=already-complete status=%s", word, existing.status)
      return
    generated = generate_with_fallback(self.llm_adapter, self.config.llm, word)
    result = self.store.add_or_update(
      VocabEntry(
        word=word,
        translation=generated.translation,
        example=generated.example,
        status=generated.status,
      )
    )
    LOG.info(
      "background enrichment finished word=%s path=%s created=%s updated=%s status=%s",
      result.word,
      result.path,
      result.created,
      result.updated,
      generated.status,
    )

  def _existing_entry(self, word: str):
    path = self.store.path_for_word(word)
    for entry in read_entries(path):
      if entry.word == word:
        return entry
    return None


def _short_reason(text: str, limit: int = 120) -> str:
  clean = " ".join(str(text or "").split())
  if len(clean) <= limit:
    return clean
  return f"{clean[:limit - 3]}..."


def active_command_words(config: AppConfig) -> tuple[str, ...]:
  wake_words: list[str] = []
  for phrase in (*config.wake.phrase_variants, config.wake.phrase):
    wake_words.extend(part for part in phrase.lower().replace("-", " ").split() if part)
  return tuple(dict.fromkeys((*config.words.command_words, *config.words.ignored_words, *wake_words)))
