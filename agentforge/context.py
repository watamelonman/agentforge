"""Context pack: the spec sections and decisions one card needs (docs/CONTEXT_PACK.md)."""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------------------
# Context pack (token efficiency). See docs/CONTEXT_PACK.md.
# Agents used to open spec/SPEC.md and docs/DECISIONS.md whole on most cards; every byte they
# read is re-sent on each later turn of the session. forge instead extracts the parts the card
# needs and puts them in the prompt; the full files stay available for grep/range reads.

MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
SPEC_REF_RE = re.compile(r"§\s*(\d+(?:\.\d+)*)")
DEC_REF_RE = re.compile(r"\bDEC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b")


def md_sections(text):
    """Split markdown into sections: [(level, title, body_with_heading)].

    A section runs to the next heading of the same or a higher level, so a `##` section
    includes its `###` children. Headings inside ``` fences are ignored."""
    lines = text.splitlines(keepends=True)
    heads, fence = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else MD_HEADING_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out = []
    for n, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j, l2, _ in heads[n + 1:]:
            if l2 <= lvl:
                end = j
                break
        out.append((lvl, title, "".join(lines[i:end]).rstrip() + "\n"))
    return out


def heading_number(title):
    """'2. Non-negotiable architecture' -> '2'; '9.4 M3 decisions' -> '9.4'; else None."""
    m = re.match(r"(\d+(?:\.\d+)*)\.?(\s|$)", title)
    return m.group(1) if m else None


def select_spec_sections(spec_text, refs, milestone):
    """Spec sections the card needs: numbered refs (§N / §N.M), plus every heading that names
    the card's milestone as a word (e.g. '### M7 — Combat core', '### 9.8 M7 decisions').
    A section already contained in a selected parent is not repeated."""
    picked = []
    mtok = re.compile(rf"(?<![A-Za-z0-9])M{milestone}(?![0-9])") if milestone not in (None, "") else None
    for lvl, title, body in md_sections(spec_text):
        num = heading_number(title)
        if (num and num in refs) or (mtok and mtok.search(title)):
            if not any(body in p for p in picked):
                picked = [p for p in picked if p not in body]   # a parent replaces its children
                picked.append(body)
    return picked


def decision_entries(dec_text):
    """{DEC-id: entry text} for '## DEC-xxx — title' entries in docs/DECISIONS.md."""
    out = {}
    for lvl, title, body in md_sections(dec_text):
        m = DEC_REF_RE.match(title)
        if m:
            out.setdefault(m.group(0), body)
    return out



def build_context(proj, card, role="work"):
    """Return the context-pack markdown for one card ('' when [context] enabled = false).

    Contents, in order (each part optional): spec sections (always_spec + §refs in the card +
    milestone headings), decisions the card names, an index of all decision titles, and the
    exact gate commands. Truncated at [context] max_chars with a visible marker."""
    if not proj.c("context", "enabled", default=True):
        return ""
    raw = card.get("raw", "")
    parts = _spec_parts(proj, card, raw) + _decision_parts(proj, raw)
    if role == "work":
        parts += _gate_command_parts(proj)
    if not parts:
        return ""
    text = "\n".join(parts)
    cap = proj.c("context", "max_chars", default=16000)
    if cap and len(text) > cap:
        text = text[:cap] + "\n[... context pack truncated at [context] max_chars; grep the source files ...]\n"
    return text


def _spec_parts(proj, card, raw):
    spec_rel = proj.c("project", "spec", default="spec/SPEC.md")
    spec_p = proj.root / spec_rel
    if not spec_p.exists():
        return []
    refs = set(str(r) for r in proj.c("context", "always_spec", default=[]))
    refs |= set(SPEC_REF_RE.findall(raw))
    secs = select_spec_sections(spec_p.read_text(), refs, card.get("milestone"))
    if not secs:
        return []
    return [f"### From {spec_rel} (only the sections this card needs)\n\n" + "\n".join(secs)]


def _decision_parts(proj, raw):
    dec_rel = proj.c("context", "decisions", default="docs/DECISIONS.md")
    dec_p = proj.root / dec_rel
    if not dec_p.exists():
        return []
    parts = []
    entries = decision_entries(dec_p.read_text())
    named = [i for i in dict.fromkeys(DEC_REF_RE.findall(raw)) if i in entries]
    if named:
        parts.append(f"### Decisions this card names (from {dec_rel})\n\n" + "\n".join(entries[i] for i in named))
    if entries and proj.c("context", "decision_index", default=False):
        titles = [l.lstrip("# ").rstrip() for l in dec_p.read_text().splitlines()
                  if l.startswith("#") and DEC_REF_RE.match(l.lstrip("# "))]
        parts.append(f"### Index of {dec_rel} (titles only; grep the id for the full entry)\n\n"
                     + "\n".join(f"- {t}" for t in titles) + "\n")
    return parts


def _gate_command_parts(proj):
    if not proj.c("context", "gate_commands", default=True):
        return []
    cmds = proj.c("gates", "cmd", default={}) or {}
    if not cmds:
        return []
    return ["### Gate commands (exactly what forge runs; already quiet, use these)\n\n"
            + "\n".join(f"- {k}: `{v}`" for k, v in cmds.items()) + "\n"]


CONTEXT_HEADER = ("## Context pack (extracted by forge)\n"
                  "These are the spec sections and decisions this card relies on. Use them instead of reading "
                  "spec/SPEC.md or docs/DECISIONS.md whole; open those files only with grep or line ranges "
                  "for something missing here.\n\n")


def with_context(tpl, context):
    """Fill {{CONTEXT}}; projects whose customized prompt lacks the placeholder get it appended."""
    block = (CONTEXT_HEADER + context) if context else ""
    if "{{CONTEXT}}" in tpl:
        return tpl.replace("{{CONTEXT}}", block)
    return tpl + ("\n\n" + block if block else "")
