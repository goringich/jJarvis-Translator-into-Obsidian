from __future__ import annotations

import logging
import os

from .audio import AudioRecorder, SpeechTranscriber, WakeWordListener
from .config import AppConfig
from .feedback import Feedback
from .llm import build_adapter, generate_with_fallback
from .markdown_store import DictionaryStore, VocabEntry
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

  def run(self, once: bool = False) -> None:
    self.store.initialize()
    LOG.info("service started pid=%s vault=%s dictionary=%s", os.getpid(), self.config.vault.path, self.config.dictionary_path)
    self.feedback.ready()
    while True:
      try:
        self.listener.wait()
        self.feedback.wake()
        self._handle_activation()
      except KeyboardInterrupt:
        LOG.info("service stopped by keyboard interrupt")
        return
      except Exception as exc:
        LOG.exception("daemon loop error: %s", exc)
        self.feedback.error(_short_reason(str(exc)))
      if once:
        LOG.info("single activation mode completed")
        return

  def _handle_activation(self) -> None:
    wav_path = self.recorder.record_wav(self.config.audio.active_window_seconds)
    try:
      transcript = self.transcriber.transcribe(wav_path)
      extraction = extract_word(
        transcript,
        command_words=self.config.words.command_words,
        allow_hyphenated=self.config.words.allow_hyphenated,
      )
      if len(extraction.candidates) > 1:
        LOG.warning(
          "multiple English word candidates recognized, using first word=%s candidates=%s ignored=%s source=%r",
          extraction.word,
          extraction.candidates,
          extraction.ignored_command_words,
          extraction.source_text,
        )
      else:
        LOG.info("recognized word=%s source=%r", extraction.word, extraction.source_text)

      generated = generate_with_fallback(self.llm_adapter, self.config.llm, extraction.word)
      LOG.info(
        "generated entry word=%s translation=%r example=%r status=%s",
        extraction.word,
        generated.translation,
        generated.example,
        generated.status,
      )
      result = self.store.add_or_update(
        VocabEntry(
          word=extraction.word,
          translation=generated.translation,
          example=generated.example,
          status=generated.status,
        )
      )
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


def _short_reason(text: str, limit: int = 120) -> str:
  clean = " ".join(str(text or "").split())
  if len(clean) <= limit:
    return clean
  return f"{clean[:limit - 3]}..."
