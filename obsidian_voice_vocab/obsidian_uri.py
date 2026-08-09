from __future__ import annotations

from pathlib import Path
import subprocess
from urllib.parse import urlencode

from .config import AppConfig
from .markdown_store import WriteResult, block_id_for_word


class ObsidianUriError(RuntimeError):
  pass


def open_dictionary_entry(config: AppConfig, result: WriteResult) -> str:
  uri = dictionary_entry_uri(config, result)
  try:
    completed = subprocess.run(
      ["xdg-open", uri],
      check=False,
      capture_output=True,
      text=True,
    )
  except OSError as exc:
    raise ObsidianUriError(f"failed to launch xdg-open for Obsidian URI: {exc}") from exc
  if completed.returncode != 0:
    stderr = " ".join((completed.stderr or "").split())
    raise ObsidianUriError(stderr or f"xdg-open exited with status {completed.returncode}")
  return uri


def dictionary_entry_uri(config: AppConfig, result: WriteResult) -> str:
  relative_path = result.path.relative_to(config.vault.path).as_posix()
  vault_name = config.vault.path.name
  if _has_advanced_uri_plugin(config):
    query = urlencode(
      {
        "vault": vault_name,
        "filepath": relative_path,
        "block": block_id_for_word(result.word),
      }
    )
    return f"obsidian://adv-uri?{query}"

  query = urlencode(
    {
      "vault": vault_name,
      "file": relative_path,
    }
  )
  return f"obsidian://open?{query}"


def _has_advanced_uri_plugin(config: AppConfig) -> bool:
  plugin_dir = config.vault.path / ".obsidian" / "plugins" / "obsidian-advanced-uri"
  return plugin_dir.exists()
