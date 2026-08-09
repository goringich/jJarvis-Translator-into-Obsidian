from __future__ import annotations

from subprocess import CompletedProcess
from unittest.mock import patch
import unittest

from obsidian_voice_vocab.cli import _read_wayland_clipboard


class CliClipboardTests(unittest.TestCase):
  def test_auto_clipboard_prefers_primary_when_present(self) -> None:
    with patch("obsidian_voice_vocab.cli.subprocess.run") as run:
      run.side_effect = [
        CompletedProcess(["wl-paste", "--no-newline", "--primary"], 0, stdout="focus\n", stderr=""),
      ]
      self.assertEqual(_read_wayland_clipboard("auto"), "focus")
      self.assertEqual(run.call_count, 1)

  def test_auto_clipboard_falls_back_to_regular_when_primary_empty(self) -> None:
    with patch("obsidian_voice_vocab.cli.subprocess.run") as run:
      run.side_effect = [
        CompletedProcess(["wl-paste", "--no-newline", "--primary"], 0, stdout="", stderr=""),
        CompletedProcess(["wl-paste", "--no-newline"], 0, stdout="clipboard\n", stderr=""),
      ]
      self.assertEqual(_read_wayland_clipboard("auto"), "clipboard")
      self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
  unittest.main()
