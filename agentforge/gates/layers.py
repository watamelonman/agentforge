"""The `layers` gate: architecture boundaries from [layers] (docs/GATES.md)."""
from __future__ import annotations

import re
from pathlib import Path

LAYER_SUFFIXES = (".c", ".h", ".cpp", ".hpp", ".cc", ".py", ".gd", ".cs", ".lua")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')     # C/C++: #include "core/x.h"
IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([\w\.]+)")         # Python: from core.x import y


def gate_layers(proj, wt):
    """Architecture boundaries: each layer may only include/import allowed layers."""
    L = proj.c("layers", default=None)
    if not L:
        return []
    root = wt / L.get("root", "src")
    rules = _LayerRules(
        allow=L.get("allow", {}),
        forbid_headers=L.get("forbid_headers", {}),
        # GDScript: preload("res://src/core/x.gd")
        res_re=re.compile(r'res://' + re.escape(L.get("root", "src")) + r'/([^"\']+)'),
        forbid_patterns={k: [re.compile(x) for x in v] for k, v in L.get("forbid_patterns", {}).items()},
    )
    if not root.exists():
        return []
    fails = []
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix not in LAYER_SUFFIXES:
            continue
        layer = f.relative_to(root).parts[0]
        if layer in rules.allow:
            fails += rules.check_file(f, wt, layer)
    return fails


class _LayerRules:
    def __init__(self, allow, forbid_headers, res_re, forbid_patterns):
        self.allow, self.forbid_headers = allow, forbid_headers
        self.res_re, self.forbid_patterns = res_re, forbid_patterns

    def check_file(self, f, wt, layer):
        fails = []
        rel = f.relative_to(wt)
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            if not _is_comment(line, f.suffix):
                for rx in self.forbid_patterns.get(layer, []):
                    if rx.search(line):
                        fails.append(f"LAYERS: {rel}:{n} ({layer}) forbidden /{rx.pattern}/: {line.strip()[:100]}")
            target = self._dependency(line, f.suffix)
            if target is not None:
                fails += self._dependency_fails(rel, n, layer, target)
        return fails

    def _dependency(self, line, suffix):
        """Path-like target this line includes/imports/preloads, or None."""
        m = self.res_re.search(line) if suffix == ".gd" else (INCLUDE_RE.match(line) or IMPORT_RE.match(line))
        if not m:
            return None
        return m.group(1).replace(".", "/") if suffix == ".py" else m.group(1)

    def _dependency_fails(self, rel, n, layer, target):
        fails = []
        head = target.split("/")[0]
        if head in self.allow and head != layer and head not in self.allow[layer]:
            fails.append(f"LAYERS: {rel}:{n} ({layer}) may not depend on {head}; allowed: {self.allow[layer]}")
        if Path(target).name in self.forbid_headers.get(layer, []):
            fails.append(f"LAYERS: {rel}:{n} ({layer}) may not include {target}")
        return fails


def _is_comment(line, suffix):
    code = line.strip()
    return code.startswith(("//", "/*", "*", "--")) or (code.startswith("#") and suffix in (".gd", ".py"))
