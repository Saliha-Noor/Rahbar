"""One JSON line per query (RAGOps D1). Goes to stdout (kubectl logs) and to a file on the
trace volume (/data/traces/<pod>.jsonl) that the report scripts read. Never breaks a request."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def prompt_hash(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]


def emit(record: dict[str, Any], trace_dir: str) -> None:
    line = json.dumps(record, default=str, ensure_ascii=False)
    with _lock:
        print(line, flush=True)
        if trace_dir:
            try:
                d = Path(trace_dir)
                d.mkdir(parents=True, exist_ok=True)
                with (d / f"{os.environ.get('HOSTNAME', 'local')}.jsonl").open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass   # a full or read-only volume must not take the API down


class Timer:
    """Per-stage latency in milliseconds."""

    def __init__(self) -> None:
        self.ms: dict[str, float] = {}
        self._t0 = time.perf_counter()

    def run(self, name: str, fn: Any, *args: Any, **kw: Any) -> Any:
        t = time.perf_counter()
        try:
            return fn(*args, **kw)
        finally:
            self.ms[name] = round(self.ms.get(name, 0.0) + (time.perf_counter() - t) * 1000, 1)

    def total(self) -> float:
        return round((time.perf_counter() - self._t0) * 1000, 1)
