"""Hosted free-tier provider (Groq, Google AI Studio, OpenRouter): OpenAI-compatible API.

The key arrives as LLM_API_KEY from a Kubernetes Secret created on the command
line. It never appears in a file you commit, and never in a log line.
Set LLM_PROVIDER=hosted, HOSTED_BASE_URL (for example https://api.groq.com/openai/v1)
and LLM_MODEL. A hosted call sends the question and the retrieved text to a third party:
say so in ADR 0004.
"""

from __future__ import annotations

import json

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...metrics_rag import TOKENS_IN, TOKENS_OUT
from ...schemas import Answer, Passage
from ...services.prompt import build_messages
from .errors import GenerationFailed


class HostedProvider:
    name = "hosted"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # hosted_base_url, llm_model, llm_api_key, temperature

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        s = self.settings
        messages = build_messages(question, passages)
        # JSON mode guarantees valid JSON, not our schema: put the schema in the prompt,
        # then validate with Pydantic.
        messages[0]["content"] += "\nJSON schema:\n" + json.dumps(Answer.model_json_schema())
        payload = {
            "model": s.llm_model,
            "messages": messages,
            "temperature": s.temperature,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {s.llm_api_key}"}
        last = "unknown error"
        for _ in range(2):  # one try, then one retry (section 3.4)
            try:
                r = httpx.post(f"{s.hosted_base_url.rstrip('/')}/chat/completions",
                               json=payload, headers=headers, timeout=120)
                r.raise_for_status()
                body = r.json()
                usage = body.get("usage", {})
                TOKENS_IN.inc(usage.get("prompt_tokens", 0))
                TOKENS_OUT.inc(usage.get("completion_tokens", 0))
                return Answer.model_validate_json(body["choices"][0]["message"]["content"])
            except (httpx.HTTPError, ValidationError, ValueError, KeyError, IndexError) as exc:
                last = type(exc).__name__  # never put request headers or the key in a message
        raise GenerationFailed(last)
