from __future__ import annotations

from pathlib import Path
import logging
import sys


def setup_logging(level: str = "INFO", log_file: Path | None = None, foreground: bool = False) -> None:
  handlers: list[logging.Handler] = []
  formatter = logging.Formatter(
    fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
  )

  if log_file is not None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    handlers.append(file_handler)

  if foreground or not handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

  logging.basicConfig(
    level=getattr(logging, level.upper(), logging.INFO),
    handlers=handlers,
    force=True,
  )

