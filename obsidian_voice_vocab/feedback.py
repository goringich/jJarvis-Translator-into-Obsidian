from __future__ import annotations

import logging
import shutil
import subprocess

from .config import AppConfig


LOG = logging.getLogger(__name__)


class Feedback:
  def __init__(self, config: AppConfig):
    self.config = config

  def ready(self) -> None:
    self.emit("Voice Vocabulary", "Listening for: Hello Obsidian", "info", "ready")

  def wake(self) -> None:
    self.emit("Voice Vocabulary", "Wake phrase detected. Say one English word.", "hint", "wake")

  def success(self, word: str) -> None:
    self.emit("Voice Vocabulary", f"Added: {word}", "ok", "success")

  def rejected(self, reason: str) -> None:
    self.emit("Voice Vocabulary", f"Rejected: {reason}", "warning", "error")

  def error(self, reason: str) -> None:
    self.emit("Voice Vocabulary", f"Error: {reason}", "error", "error")

  def emit(self, title: str, message: str, level: str, sound_name: str) -> None:
    LOG.info("feedback level=%s title=%r message=%r", level, title, message)
    self._hyprctl(title, message, level)
    self._notify_send(title, message)
    self._sound(sound_name)

  def _hyprctl(self, title: str, message: str, level: str) -> None:
    if not self.config.feedback.hyprctl_notify or not shutil.which("hyprctl"):
      return
    icon = {
      "warning": "0",
      "info": "1",
      "hint": "2",
      "error": "3",
      "ok": "5",
    }.get(level, "1")
    color = {
      "warning": "rgba(f6c177ff)",
      "info": "rgba(9ccfd8ff)",
      "hint": "rgba(c4a7e7ff)",
      "error": "rgba(eb6f92ff)",
      "ok": "rgba(9ece6aff)",
    }.get(level, "0")
    self._run(
      [
        "hyprctl",
        "notify",
        icon,
        str(self.config.feedback.timeout_ms),
        color,
        f"{title}: {message}",
      ]
    )

  def _notify_send(self, title: str, message: str) -> None:
    if not self.config.feedback.notify_send or not shutil.which("notify-send"):
      return
    self._run(["notify-send", "-t", str(self.config.feedback.timeout_ms), title, message])

  def _sound(self, sound_name: str) -> None:
    if not self.config.feedback.sound:
      return
    path = {
      "ready": self.config.feedback.ready_sound,
      "wake": self.config.feedback.wake_sound,
      "success": self.config.feedback.success_sound,
      "error": self.config.feedback.error_sound,
    }.get(sound_name)
    if path is None or not path.exists():
      return
    player = shutil.which("pw-play") or shutil.which("paplay")
    if not player:
      return
    self._run([player, str(path)])

  def _run(self, cmd: list[str]) -> None:
    try:
      subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
      LOG.debug("feedback command failed cmd=%s error=%s", cmd, exc)
