from __future__ import annotations

import unittest

from obsidian_voice_vocab.llm import LlmError, parse_model_response


class LlmParsingTests(unittest.TestCase):
  def test_parses_json_response(self) -> None:
    generated = parse_model_response(
      "sustainable",
      '{"translation":"устойчивый","example":"Sustainable habits can improve everyday life."}',
    )

    self.assertEqual(generated.translation, "устойчивый")
    self.assertEqual(generated.example, "Sustainable habits can improve everyday life.")
    self.assertEqual(generated.status, "generated")

  def test_falls_back_when_model_mixes_latin_into_translation(self) -> None:
    generated = parse_model_response(
      "sustainable",
      '{"translation":"сustainable","example":"Это сustainи-бельный продукт."}',
    )

    self.assertEqual(generated.translation, "устойчивый")
    self.assertEqual(generated.example, "I learned the word sustainable today.")
    self.assertEqual(generated.status, "llm-fallback")


if __name__ == "__main__":
  unittest.main()
