"""Ollama provider: ollama-host or ollama-incluster (section 3.5)."""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from ...config import Settings
from ...metrics_rag import TOKENS_IN, TOKENS_OUT
from ...schemas import Answer, Passage
from ...services.prompt import build_messages
from .errors import GenerationFailed


class OllamaProvider:
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings   # ollama_url, llm_model, temperature

    def generate(self, question: str, passages: list[Passage]) -> Answer:
        s = self.settings
        payload = {
            "model": s.llm_model,
            "messages": build_messages(question, passages),
            "stream": False,
            "format": Answer.model_json_schema(),   # strongest enforcement Ollama offers
            "options": {"temperature": s.temperature,
                        **({"seed": s.llm_seed} if s.llm_seed is not None else {})},
        }
        last = "unknown error"
        for _ in range(2):  # one try, then one retry (section 3.4)
            try:
                r = httpx.post(f"{s.ollama_url}/api/chat", json=payload, timeout=180)
                r.raise_for_status()
                body = r.json()
                TOKENS_IN.inc(body.get("prompt_eval_count", 0))
                TOKENS_OUT.inc(body.get("eval_count", 0))
                return Answer.model_validate_json(body["message"]["content"])
            except (httpx.HTTPError, ValidationError, ValueError, KeyError) as exc:
                last = str(exc)
        raise GenerationFailed(last)
