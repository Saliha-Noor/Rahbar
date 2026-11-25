"""Shared heading pattern: used by clean.py and chunk.py."""

import re

HEADING = re.compile(
    r"^(?:#{1,4}\s+.+"
    r"|\d{1,2}(?:\.\d{1,2})*\.?\s+[A-Z][^\n.]{2,70}"
    r"|[A-Z][A-Z &/\-]{5,80})$"
)

# Prompt-injection phrases. Verification only WARNS on these (the document is still indexed);
# the API's retrieval rail redacts them at query time (docs/RAGOPS.md, D4).
INJECTION = re.compile(
    r"(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+)?"
    r"(?:previous|prior|above|earlier|system)\s+(?:instructions?|prompts?|rules?)"
    r"|you\s+are\s+now\b|reveal\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)"
    r"|do\s+not\s+(?:tell|inform)\s+the\s+user|<\|?\s*(?:system|im_start)",
    re.I,
)
