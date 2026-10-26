#!/usr/bin/env python3
"""Fail if docs drift from the implementation.

Checks:
1. Every subcommand of the real argparse parser has a `### forge <cmd>` section in docs/CLI.md,
   every option string of that subcommand appears in its section, and every `--flag` written
   in a section exists in the parser (both directions).
2. Every forge.toml key that bin/forge and the agentforge/ package read (proj.c(...), P.get,
   L.get, a.get) and every key in every preset forge.toml appears in docs/CONFIG.md as `section.key`.
3. Every preset folder is listed in docs/PRESETS.md and in the --preset line of docs/CLI.md.
"""
import argparse
import re
import sys
import tomllib
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
forge = SourceFileLoader("forge", str(ROOT / "bin" / "forge")).load_module()
errors = []

# ---- 1. CLI
cli = (ROOT / "docs" / "CLI.md").read_text()
sections = dict(re.findall(r"^### forge (\S+).*?\n(.*?)(?=^### |^## |\Z)", cli, re.S | re.M))
ap = forge.build_parser()


def opts(parser):
    out = set()
    for a in parser._actions:
        if isinstance(a, (argparse._SubParsersAction, argparse._HelpAction)):
            continue
        out |= set(a.option_strings) or {a.dest}
    return out


sub = next(a for a in ap._actions if isinstance(a, argparse._SubParsersAction))
checks = {"(global": (ap, opts(ap))}
checks.update({name: (p, opts(p)) for name, p in sub.choices.items()})
FLAG = re.compile(r"(?<![\w-])(--?[a-zA-Z][\w-]*)")
for name, (p, real) in checks.items():
    text = sections.get(name)
    if text is None:
        errors.append(f"CLI.md: missing section '### forge {name}'")
        continue
    # Option cells = first column of table rows, e.g. "| `--parallel N`, `-j N` | ...".
    rows = [l.split("|")[1] for l in text.splitlines() if l.startswith("| `")]
    documented = {f for cell in rows for f in FLAG.findall(cell)}
    positional = {re.match(r"\s*`(\w+)`", c).group(1) for c in rows if re.match(r"\s*`(\w+)`", c)}
    for o in real:
        if o not in documented and o not in positional:
            errors.append(f"CLI.md [{name}]: option {o} undocumented")
    for o in documented - real - {"-h", "--help"}:
        errors.append(f"CLI.md [{name}]: documents {o} which the parser lacks")
for doc_cmd in sections:
    if doc_cmd not in checks:
        errors.append(f"CLI.md: documents nonexistent command '{doc_cmd}'")

# ---- 2. CONFIG
conf = (ROOT / "docs" / "CONFIG.md").read_text()
# bin/forge is a thin entry point; the code (and so the key reads) lives in agentforge/.
src = "\n".join(f.read_text() for f in [ROOT / "bin" / "forge", *sorted((ROOT / "agentforge").rglob("*.py"))])
keys = set()
for chain in re.findall(r'\.c\(((?:"[a-z_]+",\s*|vendor,\s*)+(?:"[a-z_]+")?)', src):
    parts = [x.strip().strip('"') for x in chain.split(",") if x.strip()]
    for v in forge.VENDORS:
        keys.add(".".join(v if x == "vendor" else x for x in parts))
keys |= {f"policy.{k}" for k in re.findall(r'P\.get\("([a-z_]+)"', src)}
keys |= {f"layers.{k}" if k == "root" else f"layers.{k}.<layer>" for k in re.findall(r'L\.get\("([a-z_]+)"', src)}
# a.get("k") / agent_cfg(proj, vendor).get("k") read a per-vendor table; the key must be
# documented for at least one built-in vendor or under the generic `agents.<name>` table
# (opencode vendors and keys every vendor accepts).
per_vendor = set(re.findall(r'\ba\.get\("([a-z_]+)"', src))
per_vendor |= set(re.findall(r'agent_cfg\([^)]*\)\.get\("([a-z_]+)"', src))
for k in sorted(per_vendor):
    if not any(f"`agents.{v}.{k}`" in conf for v in list(forge.VENDORS) + ["<name>"]):
        errors.append(f"CONFIG.md: per-vendor key `{k}` (a.get) undocumented under any agents.<vendor>")
keys |= {"agents.claude.bin", "agents.codex.bin", "agents.glm.bin"}
keys |= {"agents.claude.max_turns"}
for f in (ROOT / "template" / "presets").glob("*/forge.toml"):
    def walk(d, pre):
        for k, v in d.items():
            if pre in ("gates.cmd", "layers.allow", "layers.forbid_headers", "layers.forbid_patterns"):
                keys.add(pre + ".<" + ("name" if pre == "gates.cmd" else "layer") + ">")
            elif isinstance(v, dict):
                walk(v, f"{pre}.{k}" if pre else k)
            else:
                keys.add(f"{pre}.{k}")
    walk(tomllib.loads(f.read_text()), "")
for k in sorted(keys):
    if k.count(".") == 0 or k in ("agents.claude", "agents.codex", "agents.glm", "gates.cmd", "layers"):
        continue
    if f"`{k}`" not in conf:
        errors.append(f"CONFIG.md: key `{k}` undocumented")

# ---- 3. presets
presets = (ROOT / "docs" / "PRESETS.md").read_text()
for p in (ROOT / "template" / "presets").iterdir():
    if f"`{p.name}`" not in presets:
        errors.append(f"PRESETS.md: preset {p.name} not listed")
    if f"`{p.name}`" not in sections.get("init", ""):
        errors.append(f"CLI.md [init]: preset {p.name} not listed")

# ---- 4. AGENTS.md policy lists are generated from each preset's forge.toml (never drift)
import shutil, tempfile
common_agents = ROOT / "template" / "common" / "AGENTS.md"
if forge.POLICY_BEGIN not in common_agents.read_text():
    errors.append("template/common/AGENTS.md lacks forge:policy-lists markers")
else:
    for f in (ROOT / "template" / "presets").glob("*/forge.toml"):
        with tempfile.TemporaryDirectory() as td:
            shutil.copy(common_agents, Path(td) / "AGENTS.md")
            shutil.copy(f, Path(td) / "forge.toml")
            forge.render_policy_lists(td)
            text = (Path(td) / "AGENTS.md").read_text()
            block = text[text.index(forge.POLICY_BEGIN):text.index(forge.POLICY_END)]
            pol = tomllib.loads(f.read_text()).get("policy", {})
            for key in ("protected", "always_allowed", "test_globs", "scene_globs"):
                for g in pol.get(key, []):
                    if f"`{g}`" not in block:
                        errors.append(f"AGENTS.md render for {f.parent.name}: {key} entry {g} missing")
            # Nothing outside the generated block may name a path as protected/never-modify.
            outside = text.replace(block, "")
            if re.search(r"(?i)never modify", outside):
                errors.append(f"AGENTS.md: a hand-written 'never modify' list exists outside the generated block")

if errors:
    print("DOCS DRIFT:\n" + "\n".join(f"- {e}" for e in errors))
    sys.exit(1)
print(f"docs OK: {len(checks)} commands, {len(keys)} config keys checked")
