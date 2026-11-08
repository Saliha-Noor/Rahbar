"""Citation check: a citation must match a passage that was actually retrieved (section 3.4)."""

from __future__ import annotations

import re

from ..schemas import Answer, Citation, Passage


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def keep_valid_citations(answer: Answer, passages: list[Passage]) -> tuple[Answer, int]:
    """Return the answer with only valid citations (snapped to the retrieved values),
    and how many were dropped."""
    index = {(_n(p.source), _n(p.section)): p for p in passages}
    good = []
    for c in answer.citations:
        p = index.get((_n(c.source), _n(c.section)))
        if p:
            good.append(Citation(source=p.source, section=p.section, page=p.page))
    return answer.model_copy(update={"citations": good}), len(answer.citations) - len(good)
