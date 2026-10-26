"""Pull a JSON object out of free-form agent text (reviewer/audit replies)."""
from __future__ import annotations

import json
import re

def parse_json_blob(text):
    """Best-effort JSON extraction: whole text, a ```json fence, or the outermost {...}."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return None
    return None
