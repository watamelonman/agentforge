"""OpenCode `run --format json` output: text parts, cost, tokens and error events."""
from __future__ import annotations

import json

def parse_opencode_output(raw):
    """(final text, total cost, token totals, errors) from `opencode run --format json`.

    Event lines: {"type": "text"|"tool_use"|"step_start"|"step_finish"|"error", "part"|"error": ...}.
    The final answer is the text of the last message that produced text. Cost and tokens are
    summed over step_finish parts. errors = [(statusCode or None, message)]."""
    texts, order = {}, []
    cost = 0.0
    tokens = {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}
    errors = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        kind, part = ev.get("type"), ev.get("part") or {}
        if kind == "text" and part.get("text"):
            mid = part.get("messageID") or ""
            if mid not in texts:
                texts[mid] = []
                order.append(mid)
            texts[mid].append(part["text"])
        elif kind == "step_finish":
            cost += float(part.get("cost") or 0)
            tk = part.get("tokens") or {}
            cache = tk.get("cache") or {}
            for k, v in (("input", tk.get("input")), ("output", tk.get("output")),
                         ("reasoning", tk.get("reasoning")), ("cache_read", cache.get("read")),
                         ("cache_write", cache.get("write"))):
                tokens[k] += int(v or 0)
        elif kind == "error":
            err = ev.get("error") or {}
            data = err.get("data") or {}
            msg = data.get("message") or err.get("message") or err.get("name") or "error"
            # OpenCode 2.x puts the HTTP status at error.status (1.x: error.data.statusCode).
            status = data.get("statusCode") or err.get("status") or err.get("statusCode")
            errors.append((int(status) if str(status).isdigit() else None, str(msg)))
    text = "\n".join(texts[order[-1]]) if order else ""
    return text, cost, tokens, errors
