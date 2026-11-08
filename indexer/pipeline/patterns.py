"""Shared heading pattern: used by clean.py and chunk.py."""

import re

HEADING = re.compile(
    r"^(?:#{1,4}\s+.+"
    r"|\d{1,2}(?:\.\d{1,2})*\.?\s+[A-Z][^\n.]{2,70}"
    r"|[A-Z][A-Z &/\-]{5,80})$"
)
