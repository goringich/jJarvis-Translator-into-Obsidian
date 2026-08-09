from __future__ import annotations

import unittest

from obsidian_voice_vocab.config import AppConfig, FeedbackConfig, RuntimeConfig
from obsidian_voice_vocab.feedback import Feedback


class CapturingFeedback(Feedback):
  def __init__(self, config: AppConfig):
    super().__init__(config)
    self.events: list[tuple[str, str, str]] = []

  def _hyprctl(self, title: str, message: str, level: str) -> None:
    self.events.append((title, message, level))

  def _notify_send(self, title: str, message: str) -> None:
    return

  def _sound(self, sound_name: str | None) -> None:
    return


class FeedbackTests(unittest.TestCase):
  def test_wake_rejections_are_rate_limited(self) -> None:
    config = AppConfig(
      feedback=FeedbackConfig(
        sound=False,
        show_wake_rejections=True,
        min_interval_seconds=0.0,
        rejection_interval_seconds=30.0,
        dedupe_window_seconds=45.0,
      ),
      runtime=RuntimeConfig(log_file=None),
    ).expanded()
    feedback = CapturingFeedback(config)

    feedback.wake_rejected("Thank you.")
    feedback.wake_rejected("Thank you very much.")
    feedback.wake_rejected("Thank you.")

    self.assertEqual(len(feedback.events), 1)
    self.assertEqual(feedback.events[0][1], "Wake ignored: Thank you.")

  def test_wake_rejections_can_be_hidden(self) -> None:
    config = AppConfig(
      feedback=FeedbackConfig(sound=False, show_wake_rejections=False),
      runtime=RuntimeConfig(log_file=None),
    ).expanded()
    feedback = CapturingFeedback(config)

    feedback.wake_rejected("Thank you.")

    self.assertEqual(feedback.events, [])


if __name__ == "__main__":
  unittest.main()
