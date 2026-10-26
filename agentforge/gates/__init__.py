"""Gates: the checks a worker's branch must pass before review and merge (docs/GATES.md).

Order comes from [gates] order: the built-in `policy` and `layers` gates, then any project
command from [gates.cmd]. The first failing gate stops the run with its report.
"""
from __future__ import annotations

import os
import subprocess

from ..util import sh, tail
from .doccheck import doc_coverage, gd_untyped   # noqa: F401  (re-exported)
from .diff import added_lines, changed_files, removed_lines, sample_paths   # noqa: F401
from .layers import gate_layers
from .policy import PolicyRules, gate_policy   # noqa: F401


def run_gates(proj, wt, base, card):
    """Run all gates in order; stop at first failing group. Returns (ok, report)."""
    order = proj.c("gates", "order", default=["policy", "layers"])
    cmds = proj.c("gates", "cmd", default={})
    nlines = proj.c("budget", "max_gate_output_lines", default=80)
    gtimeout = proj.c("gates", "timeout_sec", default=900)
    for g in order:
        if g == "policy":
            fails = gate_policy(proj, wt, base, card)
        elif g == "layers":
            fails = gate_layers(proj, wt)
        elif g in cmds:
            try:
                r = sh(cmds[g], cwd=wt, check=False, timeout=gtimeout,
                       env=dict(os.environ, FORGE_BASE=base))
                fails = [] if r.returncode == 0 else [f"`{cmds[g]}` exited {r.returncode}:\n" +
                                                     tail(r.stdout + r.stderr, nlines)]
            except subprocess.TimeoutExpired:
                fails = [f"`{cmds[g]}` timed out after {gtimeout}s (infinite loop? slow test?)"]
        else:
            continue
        if fails:
            uniq = list(dict.fromkeys(fails))
            return False, f"GATE `{g}` FAILED:\n" + "\n".join(f"- {x}" for x in uniq[:40])
    return True, "all gates passed: " + ", ".join(order)
