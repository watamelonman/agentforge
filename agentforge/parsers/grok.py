"""Grok Build headless output: NDJSON stream lines or one pretty-printed JSON object."""
from __future__ import annotations

import json

def _grok_field(ev, *names):
    """First present key among snake_case/camelCase aliases Grok logs use interchangeably."""
    for n in names:
        if n in ev and ev[n] is not None:
            return ev[n]
    return None


def _iter_grok_json_events(raw):
    """Yield dict events from a Grok headless log, newest first.

    Two passes: (1) every line that is a JSON object on its own (streaming NDJSON), last
    line first; (2) then the last `{` from which the rest of the text parses as one object
    (`--json-schema` / `--output-format json` write one indented blob over many lines).
    Non-dict JSON and junk are skipped.

    >>> raw = 'starting\\n{"type": "tool"}\\n{"type": "result", "result": "ok"}\\n'
    >>> [e["type"] for e in _iter_grok_json_events(raw)]
    ['result', 'tool', 'result']

    (the last `{` pass finds the final line again.) A pretty-printed object yields only
    from pass 2, and only its innermost trailing object that parses on its own wins:

    >>> list(_iter_grok_json_events('log line\\n{\\n  "text": "done",\\n  "stopReason": "end"\\n}'))
    [{'text': 'done', 'stopReason': 'end'}]
    >>> list(_iter_grok_json_events(None))
    []
    """
    yield from _ndjson_objects(raw or "")
    tail_obj = _trailing_object(raw or "")
    if tail_obj is not None:
        yield tail_obj


def _ndjson_objects(text):
    """Dict objects that sit on one line each, last line first."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        if isinstance(ev, dict):
            yield ev


def _trailing_object(text):
    """The JSON value starting at the last `{` from which the rest of the text parses, if
    it is a dict. Scans backwards; stops at the first `{` that parses (dict or not)."""
    for i in range(len(text) - 1, -1, -1):
        if text[i] != "{":
            continue
        try:
            ev = json.loads(text[i:])
        except Exception:
            continue
        return ev if isinstance(ev, dict) else None
    return None


def parse_grok_output(raw):
    """(text, structured data or None, cost, is_error) from a Grok Build headless log.

    Handles the streaming-messages-json terminal `result` line, the single `--output-format
    json` / `--json-schema` object ({"text": ..., "stopReason": ..., "structuredOutput": ...})
    and `{"type":"error","message":...}`. Field names accept both snake_case and camelCase
    (`structured_output`/`structuredOutput`, `is_error`/`isError`, `total_cost_usd`/
    `totalCostUsd`, `stop_reason`/`stopReason`, `session_id`/`sessionId`).
    total_cost_usd is often absent on subscription (OAuth) traffic; 0.0 then."""
    for ev in _iter_grok_json_events(raw):
        cost = float(_grok_field(ev, "total_cost_usd", "totalCostUsd") or 0)
        if ev.get("type") == "result":
            data = _grok_field(ev, "structured_output", "structuredOutput")
            return (ev.get("result") or "", data if isinstance(data, dict) else data,
                    cost, bool(_grok_field(ev, "is_error", "isError")))
        if ev.get("type") == "error":
            return ev.get("message") or "", None, cost, True
        # json / --json-schema final object (camelCase stopReason/sessionId, or snake aliases)
        if "text" in ev and (_grok_field(ev, "stopReason", "stop_reason", "sessionId", "session_id")
                             is not None or "structuredOutput" in ev or "structured_output" in ev):
            data = _grok_field(ev, "structured_output", "structuredOutput")
            return ev.get("text") or "", data if isinstance(data, dict) else None, cost, False
    # Last resort: whole-file JSON (Grok sometimes finishes flushing after process exit)
    try:
        ev = json.loads(raw or "")
    except Exception:
        ev = None
    if isinstance(ev, dict):
        cost = float(_grok_field(ev, "total_cost_usd", "totalCostUsd") or 0)
        data = _grok_field(ev, "structured_output", "structuredOutput")
        if isinstance(data, dict) or "text" in ev:
            return (ev.get("text") or ev.get("result") or ""), data if isinstance(data, dict) else None, cost, bool(_grok_field(ev, "is_error", "isError"))
    return "", None, 0.0, False
