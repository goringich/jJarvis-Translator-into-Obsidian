from __future__ import annotations

import unittest

from obsidian_voice_vocab.audio import _max_prediction_score, _normalize_phrase, _wake_phrase_matches


class AudioWakeMatchingTests(unittest.TestCase):
  def test_normalize_phrase_strips_punctuation(self) -> None:
    self.assertEqual(_normalize_phrase("Hello, Obsidian, communication"), "hello obsidian communication")

  def test_wake_phrase_matches_prefix_with_extra_tail(self) -> None:
    self.assertTrue(_wake_phrase_matches("hello obsidian communication", "hello obsidian"))

  def test_wake_phrase_matches_exact(self) -> None:
    self.assertTrue(_wake_phrase_matches("hello obsidian", "hello obsidian"))

  def test_wake_phrase_matches_minor_misrecognition(self) -> None:
    self.assertTrue(_wake_phrase_matches("hello obsidion", "hello obsidian"))

  def test_wake_phrase_rejects_unrelated_text(self) -> None:
    self.assertFalse(_wake_phrase_matches("come on what you doing", "hello obsidian"))

  def test_max_prediction_score_handles_dicts(self) -> None:
    self.assertEqual(_max_prediction_score({"hello": 0.25, "obsidian": 0.75}), 0.75)

  def test_max_prediction_score_ignores_non_numeric_values(self) -> None:
    self.assertEqual(_max_prediction_score({"bad": "x", "good": "0.5"}), 0.5)


if __name__ == "__main__":
  unittest.main()
