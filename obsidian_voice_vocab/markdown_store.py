from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
import fcntl
import html
import os
import re

from .config import ALPHABET, AppConfig
from .normalizer import file_letter_for_word, normalize_word


BEGIN_MARKER = "<!-- ovv:begin -->"
END_MARKER = "<!-- ovv:end -->"
ENTRY_RE = re.compile(
  r'<!-- ovv:entry word="(?P<word>[^"]+)" -->\n(?P<body>.*?)\n<!-- /ovv:entry -->',
  re.DOTALL,
)
FIELD_RE_TEMPLATE = r"^[^\S\r\n]*- {field}:[^\S\r\n]*(?P<value>[^\r\n]*)[^\S\r\n]*$"


@dataclass(frozen=True)
class VocabEntry:
  word: str
  translation: str = ""
  example: str = ""
  status: str = "manual"

  def normalized(self) -> "VocabEntry":
    return VocabEntry(
      word=normalize_word(self.word),
      translation=single_line(self.translation),
      example=single_line(self.example),
      status=single_line(self.status) or "manual",
    )


@dataclass(frozen=True)
class WriteResult:
  word: str
  letter: str
  path: Path
  created: bool
  updated: bool
  count: int


class DictionaryStore:
  def __init__(self, config: AppConfig):
    self.config = config
    self.root = config.dictionary_path

  def initialize(self) -> None:
    self.root.mkdir(parents=True, exist_ok=True)
    for letter in ALPHABET:
      path = self.path_for_letter(letter)
      if not path.exists():
        self._atomic_write(path, render_file(letter, []))

  def add_or_update(self, entry: VocabEntry, overwrite_existing: bool | None = None) -> WriteResult:
    normalized = entry.normalized()
    letter = file_letter_for_word(normalized.word)
    path = self.path_for_letter(letter)
    self.root.mkdir(parents=True, exist_ok=True)
    overwrite = self.config.duplicates.overwrite_existing if overwrite_existing is None else overwrite_existing

    with self._lock_for(letter):
      entries = read_entries(path, letter)
      existing = {item.word: item for item in entries}
      created = normalized.word not in existing
      updated = False

      if created:
        existing[normalized.word] = normalized
      else:
        current = existing[normalized.word]
        merged = merge_entry(current, normalized, overwrite)
        updated = merged != current
        existing[normalized.word] = merged

      sorted_entries = sorted(existing.values(), key=lambda item: item.word)
      self._atomic_write(path, render_file(letter, sorted_entries))

    return WriteResult(
      word=normalized.word,
      letter=letter,
      path=path,
      created=created,
      updated=updated,
      count=len(sorted_entries),
    )

  def path_for_word(self, word: str) -> Path:
    return self.path_for_letter(file_letter_for_word(word))

  def path_for_letter(self, letter: str) -> Path:
    upper = letter.upper()
    if upper not in ALPHABET:
      raise ValueError(f"letter must be A-Z: {letter!r}")
    return self.root / f"{upper}.md"

  def _lock_for(self, letter: str):
    lock_path = self.root / f".{letter.upper()}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(lock_path)

  def _atomic_write(self, path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
      tmp.write(text)
      tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


class FileLock:
  def __init__(self, path: Path):
    self.path = path
    self.handle = None

  def __enter__(self) -> "FileLock":
    self.handle = self.path.open("w", encoding="utf-8")
    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
    return self

  def __exit__(self, exc_type, exc_value, traceback) -> None:
    if self.handle is not None:
      fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
      self.handle.close()


def read_entries(path: Path, letter: str | None = None) -> list[VocabEntry]:
  if not path.exists():
    return []
  text = path.read_text(encoding="utf-8")
  entries = parse_entries(text)
  if letter is None:
    return entries
  upper = letter.upper()
  return [entry for entry in entries if file_letter_for_word(entry.word) == upper]


def parse_entries(text: str) -> list[VocabEntry]:
  entries: dict[str, VocabEntry] = {}
  for match in ENTRY_RE.finditer(text):
    word = html.unescape(match.group("word")).strip()
    body = match.group("body")
    try:
      normalized_word = normalize_word(word)
    except ValueError:
      continue
    entries[normalized_word] = VocabEntry(
      word=normalized_word,
      translation=_field(body, "Translation"),
      example=_field(body, "Example"),
      status=_field(body, "Status") or "manual",
    ).normalized()
  return sorted(entries.values(), key=lambda item: item.word)


def render_file(letter: str, entries: list[VocabEntry]) -> str:
  upper = letter.upper()
  normalized_entries = sorted((entry.normalized() for entry in entries), key=lambda item: item.word)
  lines = [
    f"# {upper}",
    "",
    "> Managed by obsidian-voice-vocab. Entry numbering is regenerated after each write.",
    "",
    BEGIN_MARKER,
    "",
  ]
  for index, entry in enumerate(normalized_entries, start=1):
    escaped_word = html.escape(entry.word, quote=True)
    block_id = block_id_for_word(entry.word)
    lines.extend(
      [
        f'<!-- ovv:entry word="{escaped_word}" -->',
        f"{index}. **{entry.word}**",
        f"   - Translation: {single_line(entry.translation)}",
        f"   - Example: {single_line(entry.example)}",
        f"   - Status: {single_line(entry.status)}",
        f"   ^{block_id}",
        "<!-- /ovv:entry -->",
        "",
      ]
    )
  lines.append(END_MARKER)
  lines.append("")
  return "\n".join(lines)


def merge_entry(existing: VocabEntry, incoming: VocabEntry, overwrite: bool) -> VocabEntry:
  if overwrite or existing.status in ("queued", "llm-failed"):
    return VocabEntry(
      word=existing.word,
      translation=incoming.translation or existing.translation,
      example=incoming.example or existing.example,
      status=incoming.status or existing.status,
    ).normalized()

  return VocabEntry(
    word=existing.word,
    translation=existing.translation or incoming.translation,
    example=existing.example or incoming.example,
    status=existing.status if existing.status != "llm-failed" else incoming.status or existing.status,
  ).normalized()


def single_line(value: str) -> str:
  return " ".join(str(value or "").replace("\n", " ").split())


def block_id_for_word(word: str) -> str:
  normalized = normalize_word(word)
  safe = re.sub(r"[^a-z0-9-]+", "-", normalized.lower()).strip("-")
  return f"ovv-{safe}"


def _field(body: str, field: str) -> str:
  pattern = re.compile(FIELD_RE_TEMPLATE.format(field=re.escape(field)), re.MULTILINE)
  match = pattern.search(body)
  if not match:
    return ""
  return single_line(match.group("value"))
