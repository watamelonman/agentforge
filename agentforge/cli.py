"""forge - orchestrate Claude Code, Codex, GLM (via Claude Code), Grok Build and OpenCode agents on a spec-driven project.

Stdlib only (Python >= 3.11 for tomllib). See README.md.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .commands.agents import cmd_audit, cmd_plan, cmd_regate, cmd_reset, cmd_review
from .commands.info import cmd_gates, cmd_limits, cmd_status, cmd_up
from .commands.setup import cmd_init, cmd_sync_agents, cmd_upgrade
from .doctor import cmd_doctor
from .project import Project
from .scheduler import cmd_run


def build_parser():
    """Build the CLI parser. Kept separate so tests/check_docs.py can diff it against docs/CLI.md."""
    ap = argparse.ArgumentParser(prog="forge", description=__doc__)
    ap.add_argument("-C", dest="root", default=".", help="project root (default .)")
    ap.add_argument("--mock", action="store_true", help="use mock agents (no tokens spent)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init", help="create a project from the template")
    p.add_argument("dir"); p.add_argument("--preset", default="godot-csharp"); p.add_argument("--spec")
    p.add_argument("--no-sample", action="store_true", help="omit the preset's disposable sample code (.forge-samples)")
    p = sub.add_parser("plan", help="decompose the spec into task cards")
    p.add_argument("--spec"); p.add_argument("--milestone"); p.add_argument("--agent", help="vendor: claude, codex, glm, grok or an [agents.<name>] opencode vendor")
    p = sub.add_parser("run", help="execute ready tasks in parallel worktrees")
    p.add_argument("--parallel", "-j", type=int, default=2)
    p.add_argument("--task", nargs="*"); p.add_argument("--audit", action="store_true", help="audit when done")
    p.add_argument("--wait", action="store_true", help="when only cooling vendors block cards, sleep until one is free")
    p = sub.add_parser("up", help="run inside a tmux dashboard")
    p.add_argument("--parallel", "-j", type=int, default=2); p.add_argument("--detach", "-d", action="store_true")
    p.add_argument("--wait", action="store_true", help="passed to run")
    sub.add_parser("status", help="show task table")
    p = sub.add_parser("limits", help="show per-vendor cooldowns and allowance use")
    p.add_argument("--clear", nargs="*", metavar="VENDOR", help="lift cooldowns (all, or the named vendors)")
    p = sub.add_parser("review", help="re-run gates (+reviewer) on a task worktree")
    p.add_argument("task"); p.add_argument("--agent", help="vendor: claude, codex, glm, grok or an [agents.<name>] opencode vendor"); p.add_argument("--gates-only", action="store_true")
    p = sub.add_parser("audit", help="whole-repo audit by the monitor agent; may add FIX cards")
    p.add_argument("--agent", help="vendor: claude, codex, glm, grok or an [agents.<name>] opencode vendor")
    p = sub.add_parser("reset", help="put blocked tasks back to todo")
    p.add_argument("task", nargs="+"); p.add_argument("--hard", action="store_true", help="also discard worktree")
    p = sub.add_parser("gates", help="run gates on main vs a base ref")
    p.add_argument("--base", default="HEAD~1")
    sub.add_parser("doctor", help="check tools and CLI auth")
    sub.add_parser("sync-agents", help="regenerate AGENTS.md policy lists from forge.toml [policy]")
    p = sub.add_parser("regate", help="gates + review + merge on the existing task branch (no worker)")
    p.add_argument("task", nargs="+")
    p.add_argument("--continue", dest="cont", action="store_true", help="on failure, let workers retry")
    p = sub.add_parser("upgrade", help="add newer forge files (.forge-samples, policy lists) to a project")
    p.add_argument("--preset", default="godot-csharp")
    return ap


def main():
    """Entry point: parse args, set mock mode, dispatch to cmd_* handlers."""
    args = build_parser().parse_args()
    if args.mock:
        os.environ["FORGE_MOCK"] = "1"
    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    proj = Project(Path(args.root))
    {"plan": cmd_plan, "run": cmd_run, "up": cmd_up, "status": cmd_status, "review": cmd_review,
     "audit": cmd_audit, "reset": cmd_reset, "gates": cmd_gates, "sync-agents": cmd_sync_agents,
     "regate": cmd_regate, "upgrade": cmd_upgrade, "limits": cmd_limits}[args.cmd](proj, args)
