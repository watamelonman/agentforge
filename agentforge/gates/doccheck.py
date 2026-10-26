"""Doc-comment and GDScript static-typing checks run by the policy gate."""
from __future__ import annotations

import re

from ..util import glob_match

# A C/C++ prototype in a header: "int foo(int x);" (not a definition: no "{").
C_PROTO_RE = re.compile(r"^[A-Za-z_][\w\s\*]*\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*;")


def doc_coverage(proj, wt, paths):
    """Public C/C++ prototypes in headers and Python defs need a doc comment."""
    P = proj.c("policy", default={})
    if not P.get("doc_check", True):
        return []
    fails = []
    for path in paths:
        fp = wt / path
        if not fp.is_file():
            continue
        lines = fp.read_text(errors="replace").splitlines()
        if path.endswith((".h", ".hpp")):
            fails += _header_docs(path, lines)
        elif path.endswith(".gd") and not glob_match(path, P.get("test_globs", [])) and not path.startswith("addons/"):
            fails += _gdscript_docs(path, lines, P.get("gd_strict_typing", True))
        elif path.endswith(".py") and "/tests/" not in f"/{path}":
            fails += _python_docs(path, lines)
    return fails


def _header_docs(path, lines):
    fails = []
    for i, l in enumerate(lines):
        if not C_PROTO_RE.match(l) or l.startswith(("static", "typedef", "return")):
            continue
        prev = lines[i - 1].strip() if i else ""
        if not (prev.endswith("*/") or prev.startswith("//") or prev.startswith("*")):
            fails.append(f"DOCS: {path}:{i+1} public function lacks a doc comment: {l.strip()[:80]}")
    return fails


def _gdscript_docs(path, lines, strict_typing):
    fails = []
    for i, l in enumerate(lines):
        m = re.match(r"^(?:static )?func ([A-Za-z]\w*)", l)
        if m and not (lines[i - 1].strip().startswith("##") if i else False):
            fails.append(f"DOCS: {path}:{i+1} public func {m.group(1)} lacks a ## doc comment")
        if strict_typing:
            fails += [f"TYPING: {path}:{i+1} {e}: {l.strip()[:90]}" for e in gd_untyped(l)]
    return fails


def _python_docs(path, lines):
    fails = []
    for i, l in enumerate(lines):
        m = re.match(r"^(def|class) ([A-Za-z]\w*)", l)
        if not m or m.group(2).startswith("_"):
            continue
        nxt = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
        if not nxt.startswith(('"""', "'''", 'r"""')):
            fails.append(f"DOCS: {path}:{i+1} public {m.group(1)} {m.group(2)} lacks a docstring")
    return fails




def gd_untyped(line):
    """Static-typing lint for one GDScript line (backs up Godot's warnings-as-errors)."""
    errs = []
    m = re.match(r"^\s*(?:static\s+)?func\s+\w+\s*\((.*)\)\s*(->\s*[\w\[\], .]+)?\s*:", line)
    if m:
        for prm in filter(None, (x.strip() for x in m.group(1).split(","))):
            if ":" not in prm.split("=")[0]:
                errs.append(f"untyped parameter `{prm}`")
        if not m.group(2):
            errs.append("missing return type (-> T / -> void)")
    if re.match(r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(?:var|const)\s+\w+\s*(=(?!=)|$)", line):
        errs.append("untyped variable (use `: Type` or `:=`)")
    return errs
