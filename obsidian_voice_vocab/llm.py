from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import json
import logging
import re
import urllib.error
import urllib.request

from .config import LlmConfig


LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeneratedEntry:
  translation: str
  example: str
  status: str


class LlmError(RuntimeError):
  pass


class BaseLlmAdapter(Protocol):
  def generate(self, word: str) -> GeneratedEntry:
    ...


class DisabledLlmAdapter(BaseLlmAdapter):
  def generate(self, word: str) -> GeneratedEntry:
    return fallback_for_word(word, "llm-disabled")


class OllamaAdapter(BaseLlmAdapter):
  def __init__(self, config: LlmConfig):
    self.config = config

  def generate(self, word: str) -> GeneratedEntry:
    prompt = build_prompt(word)
    payload = {
      "model": self.config.model,
      "stream": False,
      "options": {
        "temperature": self.config.temperature,
        "num_predict": self.config.max_tokens,
      },
      "messages": [
        {
          "role": "system",
          "content": "You produce strict two-line vocabulary data and no extra text.",
        },
        {
          "role": "user",
          "content": prompt,
        },
      ],
    }
    response = _post_json(f"{self.config.endpoint}/api/chat", payload, self.config.timeout_seconds)
    content = str(response.get("message", {}).get("content", ""))
    return parse_model_response(word, content)


class OpenAICompatibleAdapter(BaseLlmAdapter):
  def __init__(self, config: LlmConfig):
    self.config = config

  def generate(self, word: str) -> GeneratedEntry:
    payload = {
      "model": self.config.model,
      "temperature": self.config.temperature,
      "max_tokens": self.config.max_tokens,
      "messages": [
        {
          "role": "system",
          "content": "You produce strict two-line vocabulary data and no extra text.",
        },
        {
          "role": "user",
          "content": build_prompt(word),
        },
      ],
    }
    response = _post_json(f"{self.config.endpoint}/v1/chat/completions", payload, self.config.timeout_seconds)
    choices = response.get("choices", [])
    if not choices:
      raise LlmError("OpenAI-compatible endpoint returned no choices")
    content = str(choices[0].get("message", {}).get("content", ""))
    return parse_model_response(word, content)


def build_adapter(config: LlmConfig) -> BaseLlmAdapter:
  provider = config.provider.lower().replace("_", "-")
  if provider in ("none", "disabled", "off"):
    return DisabledLlmAdapter()
  if provider == "ollama":
    return OllamaAdapter(config)
  if provider in ("openai-compatible", "openai", "openclaw"):
    return OpenAICompatibleAdapter(config)
  raise ValueError(f"unsupported llm.provider: {config.provider}")


def generate_with_fallback(adapter: BaseLlmAdapter, config: LlmConfig, word: str) -> GeneratedEntry:
  try:
    generated = adapter.generate(word)
    if generated.translation or generated.example:
      return generated
  except Exception as exc:
    LOG.warning("LLM generation failed for %s: %s", word, exc)

  if config.fallback_dictionary:
    return fallback_for_word(word, "llm-failed")
  return GeneratedEntry(translation="", example="", status="llm-failed")


def build_prompt(word: str) -> str:
  return (
    f'Word: "{word}"\n'
    "Return exactly two lines, no markdown, no explanations, no numbering:\n"
    "translation: <short Russian translation of the word>\n"
    f"example: <one short natural B1-B2 English sentence containing the exact word \"{word}\">"
  )


def parse_model_response(word: str, content: str) -> GeneratedEntry:
  text = _clean_response(content)
  data = _parse_json_response(text) or _parse_key_value_response(text) or _parse_two_line_response(text)
  if data is None:
    raise LlmError(f"could not parse model response: {content[:160]!r}")

  translation = _clean_field(data.get("translation", ""))
  example = _clean_field(data.get("example", ""))
  status = "generated"

  if not translation:
    status = "llm-partial"
  if example and not _example_contains_word(word, example):
    LOG.warning("Model example does not contain exact word %s: %s", word, example)
    example = ""
    status = "llm-partial" if translation else "llm-failed"

  if not translation and not example:
    raise LlmError("model response did not contain usable translation or example")

  return GeneratedEntry(translation=translation, example=example, status=status)


def fallback_for_word(word: str, status: str) -> GeneratedEntry:
  fallback = FALLBACK_TRANSLATIONS.get(word.lower(), "")
  return GeneratedEntry(translation=fallback, example="", status=status)


def _post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
  body = json.dumps(payload).encode("utf-8")
  request = urllib.request.Request(
    url,
    data=body,
    headers={"Content-Type": "application/json"},
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
      raw = response.read().decode("utf-8")
  except urllib.error.URLError as exc:
    raise LlmError(f"cannot reach local LLM endpoint {url}: {exc}") from exc
  try:
    return json.loads(raw)
  except json.JSONDecodeError as exc:
    raise LlmError(f"local LLM endpoint returned invalid JSON: {raw[:160]!r}") from exc


def _clean_response(content: str) -> str:
  text = str(content or "").strip()
  text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
  text = re.sub(r"```$", "", text).strip()
  return text


def _parse_json_response(text: str) -> dict[str, str] | None:
  try:
    value = json.loads(text)
  except json.JSONDecodeError:
    return None
  if not isinstance(value, dict):
    return None
  return {
    "translation": str(value.get("translation", "")),
    "example": str(value.get("example", "")),
  }


def _parse_key_value_response(text: str) -> dict[str, str] | None:
  data: dict[str, str] = {}
  for line in text.splitlines():
    match = re.match(r"^\s*(translation|translate|перевод|example|sentence|пример)\s*:\s*(.*?)\s*$", line, re.IGNORECASE)
    if not match:
      continue
    key = match.group(1).lower()
    value = match.group(2)
    if key in ("translation", "translate", "перевод"):
      data["translation"] = value
    else:
      data["example"] = value
  if "translation" in data or "example" in data:
    return data
  return None


def _parse_two_line_response(text: str) -> dict[str, str] | None:
  lines = [_clean_field(line) for line in text.splitlines() if _clean_field(line)]
  if len(lines) < 2:
    return None
  return {
    "translation": lines[0],
    "example": lines[1],
  }


def _clean_field(value: str) -> str:
  text = " ".join(str(value or "").replace("\n", " ").split())
  text = text.strip(" -_*`\"'")
  return text


def _example_contains_word(word: str, example: str) -> bool:
  pattern = re.compile(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", re.IGNORECASE)
  return bool(pattern.search(example))


FALLBACK_TRANSLATIONS = {
  "ability": "способность",
  "able": "способный",
  "accept": "принимать",
  "achieve": "достигать",
  "active": "активный",
  "adapt": "адаптироваться",
  "add": "добавлять",
  "advice": "совет",
  "agree": "соглашаться",
  "allow": "позволять",
  "answer": "ответ",
  "appear": "появляться",
  "apply": "применять",
  "ask": "спрашивать",
  "avoid": "избегать",
  "basic": "базовый",
  "believe": "верить",
  "build": "строить",
  "change": "изменение",
  "clear": "ясный",
  "common": "общий",
  "compare": "сравнивать",
  "complete": "полный",
  "create": "создавать",
  "daily": "ежедневный",
  "decide": "решать",
  "develop": "развивать",
  "different": "разный",
  "difficult": "сложный",
  "example": "пример",
  "explain": "объяснять",
  "focus": "фокусироваться",
  "improve": "улучшать",
  "include": "включать",
  "learn": "учиться",
  "local": "локальный",
  "manage": "управлять",
  "natural": "естественный",
  "practice": "практика",
  "prepare": "готовить",
  "reliable": "надёжный",
  "simple": "простой",
  "stable": "стабильный",
  "sustainable": "устойчивый",
  "system": "система",
  "useful": "полезный",
  "voice": "голос",
  "word": "слово",
}
