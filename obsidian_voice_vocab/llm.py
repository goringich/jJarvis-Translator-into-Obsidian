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
    last_error: Exception | None = None
    for prompt in (build_prompt(word), build_retry_prompt(word), build_final_retry_prompt(word)):
      payload = {
        "model": self.config.model,
        "stream": False,
        "format": "json",
        "options": {
          "temperature": self.config.temperature,
          "num_predict": self.config.max_tokens,
        },
        "messages": [
          {
            "role": "system",
            "content": (
              "You are a strict bilingual vocabulary generator. Return only valid JSON. "
              "The translation value must be short Russian text. "
              "The example value must be one natural English context sentence."
            ),
          },
          {
            "role": "user",
            "content": prompt,
          },
        ],
      }
      response = _post_json(f"{self.config.endpoint}/api/chat", payload, self.config.timeout_seconds)
      content = str(response.get("message", {}).get("content", ""))
      try:
        return parse_model_response(word, content)
      except LlmError as exc:
        last_error = exc
        LOG.warning("Ollama response rejected for %s, retrying if possible: %s", word, exc)
    raise LlmError(str(last_error or "Ollama response did not contain usable vocabulary data"))


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
    f"English word: {word}\n"
    "Return JSON only with exactly these keys: translation, example.\n"
    "translation: a short Russian translation in Cyrillic, no English letters.\n"
    f'example: one natural B1-B2 English sentence that uses "{word}" in real context.\n'
    "Do not explain the word. Do not write about learning, studying, saying, or using the word as a word.\n"
    f'Good format: {{"translation":"короткий перевод","example":"A clear sentence with {word} in everyday context."}}'
  )


def build_retry_prompt(word: str) -> str:
  return (
    "Ты переводчик для личного словаря Obsidian.\n"
    f"Слово: {word}\n"
    "Ответь только JSON-объектом без markdown и без пояснений.\n"
    "Поле translation: короткий перевод на русский язык кириллицей.\n"
    f"Поле example: одно короткое естественное английское предложение уровня B1-B2 со словом {word} в жизненном контексте.\n"
    "Нельзя писать фразы про изучение слова или само слово как объект.\n"
    f'Формат: {{"translation":"перевод","example":"The team made a {word} plan for the project."}}'
  )


def build_final_retry_prompt(word: str) -> str:
  return (
    f'Only JSON: {{"translation":"...","example":"..."}}\n'
    f'Word: "{word}".\n'
    "Rules:\n"
    "- translation is Russian Cyrillic only.\n"
    f'- example is one English sentence containing "{word}".\n'
    "- example must show meaning through context.\n"
    "- do not mention vocabulary, learning, studying, saying, translating, or the word itself."
  )


def parse_model_response(word: str, content: str) -> GeneratedEntry:
  text = _clean_response(content)
  data = _parse_json_response(text) or _parse_key_value_response(text) or _parse_two_line_response(text)
  if data is None:
    raise LlmError(f"could not parse model response: {content[:160]!r}")

  fallback = FALLBACK_TRANSLATIONS.get(word.lower(), "")
  translation = _clean_field(data.get("translation", ""))
  example = _clean_field(data.get("example", ""))
  status = "generated"

  if translation and not _looks_like_russian_translation(translation):
    LOG.warning("Model translation is not a clean Russian translation for %s: %s", word, translation)
    translation = ""

  if not translation:
    status = "llm-partial"
  if example and not _example_contains_word(word, example):
    LOG.warning("Model example does not contain exact word %s: %s", word, example)
    example = ""
    status = "llm-partial" if translation else "llm-failed"
  if example and not _looks_like_english_example(word, example):
    LOG.warning("Model example is not a useful English context sentence for %s: %s", word, example)
    example = ""
    status = "llm-partial" if translation else "llm-failed"

  if not translation:
    if fallback:
      translation = fallback
      status = "llm-fallback"

  if fallback and status in ("llm-partial", "llm-failed"):
    translation = fallback
    status = "llm-fallback"

  if not example:
    example = fallback_example(word)
    status = "llm-fallback" if translation else "llm-failed"

  if not translation and not example:
    raise LlmError("model response did not contain usable translation or example")

  return GeneratedEntry(translation=translation, example=example, status=status)


def fallback_for_word(word: str, status: str) -> GeneratedEntry:
  fallback = FALLBACK_TRANSLATIONS.get(word.lower(), "")
  return GeneratedEntry(translation=fallback, example=fallback_example(word), status=status)


def fallback_example(word: str) -> str:
  example = FALLBACK_EXAMPLES.get(word.lower())
  if example:
    return example
  return f"This example sentence needs a better context for {word}."


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


def _looks_like_russian_translation(text: str) -> bool:
  if not re.search(r"[А-Яа-яЁё]", text):
    return False
  return not bool(re.search(r"[A-Za-z]", text))


def _looks_like_english_example(word: str, text: str) -> bool:
  if re.search(r"[А-Яа-яЁё]", text):
    return False
  if not re.search(r"[A-Za-z]", text):
    return False
  if not re.search(r"[.!?]$", text.strip()):
    return False
  lowered = text.lower()
  banned_patterns = (
    rf"\bthe word {re.escape(word.lower())}\b",
    rf"\bword {re.escape(word.lower())}\b",
    r"\blearn(?:ed|ing)?\b",
    r"\bstud(?:y|ied|ying)\b",
    r"\btranslate(?:d|s|ing)?\b",
    r"\bvocabulary\b",
    r"\bdictionary\b",
  )
  return not any(re.search(pattern, lowered) for pattern in banned_patterns)


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


FALLBACK_EXAMPLES = {
  "ability": "Her ability to stay calm helped the whole team.",
  "accept": "He decided to accept the new job offer.",
  "achieve": "They worked hard to achieve their goal.",
  "adapt": "Small companies must adapt quickly to change.",
  "advice": "She gave me useful advice before the interview.",
  "agree": "I agree with your plan for the weekend.",
  "allow": "This app will allow users to save notes faster.",
  "appear": "Dark clouds began to appear over the city.",
  "avoid": "Try to avoid making the same mistake twice.",
  "basic": "The course starts with basic grammar rules.",
  "build": "They want to build a small house near the lake.",
  "clear": "Please give me a clear answer by Friday.",
  "compare": "We need to compare both options before we decide.",
  "complete": "She stayed late to complete the report.",
  "create": "The designer will create a new logo for the cafe.",
  "daily": "A daily walk can improve your mood.",
  "decide": "We must decide where to meet tonight.",
  "develop": "The team will develop a safer payment system.",
  "difficult": "This question is difficult, but I can solve it.",
  "elephant": "The elephant walked slowly across the dry grass.",
  "example": "This example shows how the rule works.",
  "explain": "Can you explain the problem in simple words?",
  "focus": "I cannot focus when the room is noisy.",
  "improve": "Regular practice can improve your pronunciation.",
  "include": "The price should include breakfast and coffee.",
  "learn": "Children learn new habits from their parents.",
  "manage": "She can manage a large project under pressure.",
  "natural": "His speech sounded natural and relaxed.",
  "practice": "Daily practice made her more confident.",
  "prepare": "We need to prepare dinner before the guests arrive.",
  "reliable": "A reliable car is important for long trips.",
  "simple": "The teacher gave a simple explanation.",
  "stable": "The ladder must be stable before you climb it.",
  "sustainable": "Sustainable farming protects the soil for future crops.",
  "useful": "This tool is useful for quick calculations.",
  "voice": "Her voice sounded calm during the call.",
}
