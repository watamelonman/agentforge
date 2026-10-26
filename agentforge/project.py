"""A forge project (forge.toml + .forge/ layout + state.json) and the process-wide locks."""
from __future__ import annotations

import json
import os
import threading
import tomllib
from pathlib import Path

from .util import die, now

STATE_LOCK = threading.Lock()   # guards read-modify-write of .forge/state.json
MERGE_LOCK = threading.Lock()   # serializes the sync + fast-forward merge into main
STOP = threading.Event()        # set by SIGTERM or budget.max_agent_runs: finish, start nothing new


class Project:
    """A forge project: config (forge.toml), paths under .forge/, and thread-safe state."""
    def __init__(self, root: Path):
        self.root = root.resolve()
        cfg_path = self.root / "forge.toml"
        if not cfg_path.exists():
            die(f"no forge.toml in {self.root} (run `forge init` first or use -C)")
        self.cfg = tomllib.loads(cfg_path.read_text())
        self.dir = self.root / ".forge"
        self.logs = self.dir / "logs"
        self.wts = self.dir / "worktrees"
        for d in (self.logs, self.wts):
            d.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.main = self.cfg.get("project", {}).get("main_branch", "main")
        self.mock = os.environ.get("FORGE_MOCK") == "1"

    # config helpers
    def c(self, *keys, default=None):
        """Nested config lookup: c('agents','claude','model', default=...)."""
        node = self.cfg
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    # state
    def load_state(self):
        """Read .forge/state.json (or a fresh state)."""
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"tasks": {}, "total_usd": 0.0, "agent_runs": 0}

    def update_state(self, fn):
        """Read-modify-write state under STATE_LOCK with an atomic rename (crash-safe)."""
        with STATE_LOCK:
            st = self.load_state()
            fn(st)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(st, indent=2))
            tmp.replace(self.state_path)
            return st

    def task_state(self, tid):
        """State dict for one task (status todo / 0 attempts if never seen)."""
        return self.load_state()["tasks"].get(tid, {"status": "todo", "attempts": 0})

    def set_task(self, tid, **kw):
        """Update task fields; `event=` dict is appended to its history with a timestamp."""
        def f(st):
            t = st["tasks"].setdefault(tid, {"status": "todo", "attempts": 0, "history": []})
            hist = kw.pop("event", None)
            t.update(kw)
            if hist:
                t.setdefault("history", []).append({"t": now(), **hist})
        self.update_state(f)

    def event(self, msg):
        """Print and append one line to .forge/logs/events.log (the human timeline)."""
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with open(self.logs / "events.log", "a") as fh:
            fh.write(line + "\n")

    def prompt(self, name):
        """Load prompts/<name>.md from the project (projects can customize prompts)."""
        return (self.root / "prompts" / f"{name}.md").read_text()


class ConfigView:
    """Tiny stand-in for Project where only .c() is needed (doctor runs without a Project)."""
    def __init__(self, cfg):
        self.cfg, self.mock = cfg, False
    c = Project.c
