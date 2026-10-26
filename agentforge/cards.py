"""Task cards: tasks/*.md files with TOML front matter between +++ lines (docs/TASKS.md)."""
from __future__ import annotations

import json
import re
import tomllib

CARD_RE = re.compile(r"^\+\+\+\n(.*?)\n\+\+\+\n?(.*)$", re.S)


def load_cards(proj):
    """Parse tasks/*.md (TOML front matter between +++ lines) into dicts keyed by id.

    Files without valid front matter are skipped silently so notes can live in tasks/ too.
    Defaults applied here are the documented card defaults (docs/TASKS.md)."""
    cards = {}
    for p in sorted((proj.root / "tasks").glob("*.md")):
        m = CARD_RE.match(p.read_text())
        if not m:
            continue
        meta = tomllib.loads(m.group(1))
        meta.setdefault("deps", [])
        meta.setdefault("owns", [])
        meta.setdefault("docs", [])
        meta.setdefault("agent", "any")
        meta.setdefault("milestone", 1)
        meta.setdefault("tests_required", True)
        meta.setdefault("may_edit_tests", False)
        meta.setdefault("scene_edits", False)
        meta["path"] = p
        meta["body"] = m.group(2)
        meta["raw"] = p.read_text()
        cards[meta["id"]] = meta
    return cards


def toml_val(v):
    """Serialize a scalar/list to TOML (tomllib is read-only; cards need only these types)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(toml_val(x) for x in v) + "]"
    return json.dumps(str(v))


def write_card(proj, t):
    """Write a planner/auditor task dict as tasks/<id>-<slug>.md; returns the path."""
    slug = re.sub(r"[^a-z0-9]+", "-", t["title"].lower()).strip("-")[:40]
    keys = ["id", "title", "milestone", "deps", "agent", "owns", "docs",
            "tests_required", "may_edit_tests", "scene_edits"]
    meta = "\n".join(f"{k} = {toml_val(t[k])}" for k in keys if k in t)
    body = f"## Goal\n{t.get('goal', '').strip()}\n\n## Acceptance criteria\n"
    body += "".join(f"- [ ] {a}\n" for a in t.get("acceptance", []))
    if t.get("notes"):
        body += f"\n## Notes\n{t['notes'].strip()}\n"
    path = proj.root / "tasks" / f"{t['id']}-{slug}.md"
    path.write_text(f"+++\n{meta}\n+++\n{body}")
    return path
