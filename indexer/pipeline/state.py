"""The ingestion manifest: what is indexed, from which file, in how many chunks.

One JSON file per collection on the PVC (/corpus/_state/<collection>.json). It is the
memory that makes ingestion incremental: an unchanged file is skipped, a changed one
replaces only its own chunks, a missing one has its chunks removed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class State:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data
        self.docs: dict[str, dict[str, Any]] = data.setdefault("docs", {})

    @classmethod
    def load(cls, state_dir: str, collection: str) -> State:
        path = Path(state_dir) / f"{collection}.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["collection"] = collection
        return cls(path, data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crashed Job never leaves half a manifest

    def reset(self) -> None:
        self.docs.clear()

    def find(self, key: str) -> str | None:
        """Look a document up by doc_id or by source file name."""
        if key in self.docs:
            return key
        for doc_id, d in self.docs.items():
            if d.get("source") == key:
                return doc_id
        return None
