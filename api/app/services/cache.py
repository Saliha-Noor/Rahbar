"""Semantic cache in Redis (section 3.3). Keys carry the index_id, so a re-index
orphans every old entry: the indexer cannot reach Redis (NetworkPolicy), and does not need to."""

from __future__ import annotations

import json
import math
import uuid
from typing import Any, cast

import redis

from ..config import Settings


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class SemanticCache:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.r = redis.Redis(host=settings.redis_host, port=settings.redis_port,
                             socket_timeout=1, decode_responses=True)

    def ping(self) -> bool:
        return bool(self.r.ping())

    def lookup(self, vec: list[float], index_id: str) -> tuple[dict[str, Any] | None, float]:
        best: dict[str, Any] | None = None
        best_sim = 0.0
        try:
            for key in self.r.scan_iter(f"cache:{index_id}:*", count=200):
                raw = cast("str | None", self.r.get(key))
                if not raw:
                    continue
                entry = json.loads(raw)
                sim = _cos(vec, entry["vec"])
                if sim > best_sim:
                    best, best_sim = entry, sim
        except redis.RedisError:
            return None, 0.0  # the cache is best-effort; never break an answer
        if best and best_sim >= self.settings.cache_threshold:
            return best["response"], best_sim
        return None, best_sim

    def store(self, vec: list[float], response: dict[str, Any], index_id: str) -> None:
        try:
            self.r.setex(f"cache:{index_id}:{uuid.uuid4().hex}", self.settings.cache_ttl,
                         json.dumps({"vec": vec, "response": response}))
        except redis.RedisError:
            pass
