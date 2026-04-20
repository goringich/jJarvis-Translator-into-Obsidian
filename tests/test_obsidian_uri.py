from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from obsidian_voice_vocab.config import AppConfig, RuntimeConfig, VaultConfig, WordConfig
from obsidian_voice_vocab.markdown_store import WriteResult
from obsidian_voice_vocab.obsidian_uri import dictionary_entry_uri


class ObsidianUriTests(unittest.TestCase):
  def test_dictionary_entry_uri_falls_back_to_core_open(self) -> None:
    with TemporaryDirectory() as tmp:
      vault = Path(tmp) / "Obsidian"
      english = vault / "English"
      english.mkdir(parents=True)
      config = AppConfig(
        vault=VaultConfig(path=vault, dictionary_folder="English"),
        words=WordConfig(max_candidates=1),
        runtime=RuntimeConfig(log_file=None),
      ).expanded()
      result = WriteResult(
        word="sustainable",
        letter="S",
        path=english / "S.md",
        created=True,
        updated=False,
        count=1,
      )
      self.assertEqual(
        dictionary_entry_uri(config, result),
        "obsidian://open?vault=Obsidian&file=English%2FS.md",
      )

  def test_dictionary_entry_uri_uses_advanced_uri_when_plugin_exists(self) -> None:
    with TemporaryDirectory() as tmp:
      vault = Path(tmp) / "Obsidian"
      english = vault / "English"
      plugin = vault / ".obsidian" / "plugins" / "obsidian-advanced-uri"
      english.mkdir(parents=True)
      plugin.mkdir(parents=True)
      config = AppConfig(
        vault=VaultConfig(path=vault, dictionary_folder="English"),
        words=WordConfig(max_candidates=1),
        runtime=RuntimeConfig(log_file=None),
      ).expanded()
      result = WriteResult(
        word="well-being",
        letter="W",
        path=english / "W.md",
        created=True,
        updated=False,
        count=1,
      )
      self.assertEqual(
        dictionary_entry_uri(config, result),
        "obsidian://adv-uri?vault=Obsidian&filepath=English%2FW.md&block=ovv-well-being",
      )


if __name__ == "__main__":
  unittest.main()
