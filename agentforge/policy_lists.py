"""AGENTS.md policy lists and .claude deny rules, generated from forge.toml [policy]."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

POLICY_BEGIN = "<!-- forge:policy-lists BEGIN"
POLICY_END = "<!-- forge:policy-lists END -->"


def render_policy_lists(root):
    """Rewrite the AGENTS.md block between the forge:policy-lists markers from forge.toml [policy].

    AGENTS.md is what agents read; forge.toml is what the gates enforce. Generating the
    prose lists from the config means the two can never disagree (tests/check_docs.py
    checks every preset). Returns True if AGENTS.md changed.
    """
    agents = Path(root) / "AGENTS.md"
    text = agents.read_text()
    if POLICY_BEGIN not in text or POLICY_END not in text:
        raise SystemExit(f"forge: {agents} has no forge:policy-lists markers; see docs/PRESETS.md")
    pol = tomllib.loads((Path(root) / "forge.toml").read_text()).get("policy", {})
    fmt = lambda xs: ", ".join(f"`{x}`" for x in xs) or "(none)"
    block = (f"{POLICY_BEGIN} (generated from forge.toml [policy] by `forge sync-agents`; do not edit by hand) -->\n"
             f"- Touch only files matching the card's `owns` globs, plus the always-allowed paths\n"
             f"  {fmt(pol.get('always_allowed', ['docs/**', 'CHANGELOG.md']))}, and **new** test files under\n"
             f"  {fmt(pol.get('test_globs', ['tests/**']))}. Anything else fails the SCOPE gate.\n"
             f"- Never modify these protected paths: {fmt(pol.get('protected', []))}.\n"
             f"  If one of them is wrong, say so in your final message under `SPEC/INFRA ISSUES`.\n"
             + (f"- Editor-owned files {fmt(pol['scene_globs'])} may only be changed by cards with\n"
                f"  `scene_edits = true`, and only in small diffs (see docs/ENGINE.md).\n"
                if pol.get("scene_globs") else "")
             + POLICY_END)
    start = text.index(POLICY_BEGIN)
    end = text.index(POLICY_END) + len(POLICY_END)
    new = text[:start] + block + text[end:]
    changed = new != text
    if changed:
        agents.write_text(new)
    # Same list for Claude's own permission layer: Edit/Write deny rules mirror `protected`.
    settings = Path(root) / ".claude" / "settings.json"
    if settings.exists():
        cfg = json.loads(settings.read_text())
        deny = [d for d in cfg.get("permissions", {}).get("deny", [])
                if not d.startswith(("Edit(", "Write("))]
        # Anchor to the project root ("/glob" = relative to the project in Claude Code): forge's
        # gate matches `protected` from the root, but Claude treats a bare "tools/**" as matching
        # any nested, case-insensitive "Tools/" dir too (e.g. Game.Core.Tests/Tools/).
        deny += [f"{t}(/{g.lstrip('/')})" for g in pol.get("protected", []) for t in ("Edit", "Write")]
        if cfg.get("permissions", {}).get("deny") != deny:
            cfg.setdefault("permissions", {})["deny"] = deny
            settings.write_text(json.dumps(cfg, indent=2) + "\n")
            changed = True
    return changed
