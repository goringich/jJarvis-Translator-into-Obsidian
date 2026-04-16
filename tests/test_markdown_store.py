from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from obsidian_voice_vocab.config import AppConfig, DuplicateConfig, RuntimeConfig, VaultConfig, WordConfig
from obsidian_voice_vocab.markdown_store import DictionaryStore, VocabEntry, parse_entries, render_file
from obsidian_voice_vocab.normalizer import extract_word, file_letter_for_word, normalize_word
from obsidian_voice_vocab.daemon import VoiceVocabularyDaemon


class MarkdownStoreTests(unittest.TestCase):
  def test_render_parse_round_trip_sorted(self) -> None:
    rendered = render_file(
      "S",
      [
        VocabEntry("sustain", "поддерживать", "I sustain my focus.", "generated"),
        VocabEntry("simple", "простой", "This is a simple task.", "generated"),
      ],
    )

    self.assertLess(rendered.index("1. **simple**"), rendered.index("2. **sustain**"))
    entries = parse_entries(rendered)
    self.assertEqual([entry.word for entry in entries], ["simple", "sustain"])
    self.assertEqual(entries[0].translation, "простой")
    self.assertEqual(entries[1].example, "I sustain my focus.")

  def test_store_adds_to_correct_letter_file_and_renumbers(self) -> None:
    with TemporaryDirectory() as tmp:
      config = _config(Path(tmp))
      store = DictionaryStore(config)
      store.initialize()

      store.add_or_update(VocabEntry("zebra", "зебра", "A zebra stands there.", "manual"))
      store.add_or_update(VocabEntry("apple", "яблоко", "An apple is on the table.", "manual"))
      store.add_or_update(VocabEntry("anchor", "якорь", "The anchor is heavy.", "manual"))

      a_text = (Path(tmp) / "vault" / "English" / "A.md").read_text(encoding="utf-8")
      z_text = (Path(tmp) / "vault" / "English" / "Z.md").read_text(encoding="utf-8")

      self.assertIn("1. **anchor**", a_text)
      self.assertIn("2. **apple**", a_text)
      self.assertNotIn("3.", a_text)
      self.assertIn("1. **zebra**", z_text)

  def test_duplicate_policy_preserves_existing_non_empty_fields(self) -> None:
    with TemporaryDirectory() as tmp:
      config = _config(Path(tmp), overwrite=False)
      store = DictionaryStore(config)
      store.initialize()

      store.add_or_update(VocabEntry("stable", "стабильный", "The system is stable.", "manual"))
      result = store.add_or_update(VocabEntry("stable", "устойчивый", "Stable habits help.", "generated"))

      text = (Path(tmp) / "vault" / "English" / "S.md").read_text(encoding="utf-8")
      entries = parse_entries(text)
      self.assertFalse(result.created)
      self.assertFalse(result.updated)
      self.assertEqual(entries[0].translation, "стабильный")
      self.assertEqual(entries[0].example, "The system is stable.")

  def test_duplicate_overwrite_uses_non_empty_new_fields(self) -> None:
    with TemporaryDirectory() as tmp:
      config = _config(Path(tmp), overwrite=True)
      store = DictionaryStore(config)
      store.initialize()

      store.add_or_update(VocabEntry("stable", "стабильный", "The system is stable.", "manual"))
      result = store.add_or_update(VocabEntry("stable", "устойчивый", "", "generated"))

      text = (Path(tmp) / "vault" / "English" / "S.md").read_text(encoding="utf-8")
      entries = parse_entries(text)
      self.assertTrue(result.updated)
      self.assertEqual(entries[0].translation, "устойчивый")
      self.assertEqual(entries[0].example, "The system is stable.")

  def test_letter_and_word_normalization(self) -> None:
    self.assertEqual(normalize_word(" Sustainable! "), "sustainable")
    self.assertEqual(file_letter_for_word("sustainable"), "S")
    self.assertEqual(file_letter_for_word("well-being"), "W")

  def test_extract_word_ignores_command_words(self) -> None:
    extraction = extract_word("please add sustainable", ("please", "add"), allow_hyphenated=True)
    self.assertEqual(extraction.word, "sustainable")
    self.assertEqual(extraction.ignored_command_words, ("please", "add"))

  def test_active_command_words_ignore_wake_phrase_remnants(self) -> None:
    with TemporaryDirectory() as tmp:
      daemon = VoiceVocabularyDaemon(_config(Path(tmp)))
      extraction = extract_word("hello obsidian reliable", daemon._active_command_words(), allow_hyphenated=True)
      self.assertEqual(extraction.word, "reliable")
      self.assertEqual(extraction.ignored_command_words, ("hello", "obsidian"))

  def test_rendered_numbering_is_sequential_after_parse(self) -> None:
    rendered = render_file("B", [VocabEntry("better"), VocabEntry("basic"), VocabEntry("build")])
    numbers = re.findall(r"^(\d+)\. \*\*", rendered, flags=re.MULTILINE)
    self.assertEqual(numbers, ["1", "2", "3"])


def _config(tmp: Path, overwrite: bool = False) -> AppConfig:
  vault = tmp / "vault"
  vault.mkdir()
  return AppConfig(
    vault=VaultConfig(path=vault, dictionary_folder="English"),
    duplicates=DuplicateConfig(overwrite_existing=overwrite),
    words=WordConfig(max_candidates=1),
    runtime=RuntimeConfig(log_file=None),
  ).expanded()


if __name__ == "__main__":
  unittest.main()
