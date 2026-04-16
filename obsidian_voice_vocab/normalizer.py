from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


WORD_RE = re.compile(r"[A-Za-z]+(?:-[A-Za-z]+)*")


@dataclass(frozen=True)
class WordExtraction:
  word: str
  source_text: str
  candidates: tuple[str, ...]
  ignored_command_words: tuple[str, ...]


class WordExtractionError(ValueError):
  pass


def normalize_transcript(text: str) -> str:
  normalized = unicodedata.normalize("NFKC", text)
  normalized = normalized.replace("’", "'").replace("`", "'")
  return " ".join(normalized.strip().split())


def extract_word(
  text: str,
  command_words: tuple[str, ...],
  allow_hyphenated: bool = True,
  singularize_simple_plurals: bool = False,
) -> WordExtraction:
  source = normalize_transcript(text)
  if not source:
    raise WordExtractionError("speech recognition returned empty text")

  raw_candidates = [match.group(0).lower().strip("-") for match in WORD_RE.finditer(source)]
  candidates = tuple(
    _normalize_candidate(candidate, singularize_simple_plurals)
    for candidate in raw_candidates
    if _valid_word(candidate, allow_hyphenated)
  )
  if not candidates:
    raise WordExtractionError(f"no valid English word found in recognized text: {source!r}")

  command_set = set(command_words)
  ignored = tuple(candidate for candidate in candidates if candidate in command_set)
  usable = tuple(candidate for candidate in candidates if candidate not in command_set)
  if not usable:
    raise WordExtractionError(f"only command words were recognized: {', '.join(candidates)}")

  return WordExtraction(
    word=usable[0],
    source_text=source,
    candidates=usable,
    ignored_command_words=ignored,
  )


def file_letter_for_word(word: str) -> str:
  normalized = normalize_word(word)
  first = normalized[0].upper()
  if first < "A" or first > "Z":
    raise ValueError(f"word must start with an English letter: {word!r}")
  return first


def normalize_word(word: str, singularize_simple_plurals: bool = False) -> str:
  text = normalize_transcript(word).lower()
  matches = WORD_RE.findall(text)
  if not matches:
    raise ValueError(f"invalid English word: {word!r}")
  candidate = matches[0].lower().strip("-")
  if not _valid_word(candidate, True):
    raise ValueError(f"invalid English word: {word!r}")
  return _normalize_candidate(candidate, singularize_simple_plurals)


def _normalize_candidate(candidate: str, singularize_simple_plurals: bool) -> str:
  if not singularize_simple_plurals:
    return candidate
  return _singularize_simple_plural(candidate)


def _valid_word(candidate: str, allow_hyphenated: bool) -> bool:
  if not candidate:
    return False
  if "--" in candidate:
    return False
  if not allow_hyphenated and "-" in candidate:
    return False
  return bool(re.fullmatch(r"[a-z]+(?:-[a-z]+)*", candidate))


def _singularize_simple_plural(candidate: str) -> str:
  if "-" in candidate or len(candidate) < 4:
    return candidate
  exceptions = {"news", "series", "species", "this", "his", "was", "is", "us", "bus"}
  if candidate in exceptions:
    return candidate
  if candidate.endswith("ies") and len(candidate) > 4:
    return f"{candidate[:-3]}y"
  for suffix in ("ches", "shes", "sses", "xes", "zes"):
    if candidate.endswith(suffix) and len(candidate) > len(suffix) + 1:
      return candidate[:-2]
  if candidate.endswith("s") and not candidate.endswith(("ss", "us", "is")):
    return candidate[:-1]
  return candidate
