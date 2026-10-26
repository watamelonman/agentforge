"""bubblewrap sandbox around a CLI that has no OS sandbox of its own (OpenCode, opt-in Codex)."""
from __future__ import annotations

import shutil
from pathlib import Path

# State dirs OpenCode writes to (auth, sessions, plugin cache); writable inside its bwrap sandbox.
OPENCODE_RW_DEFAULT = ("~/.local/share/opencode", "~/.local/state/opencode", "~/.cache/opencode",
                       "~/.config/opencode")


def sandbox_wrap(proj, a, cwd, inner, writable_cwd, ro_files=()):
    """Run `inner` inside bubblewrap: the whole filesystem read-only, the worktree writable
    (workers only), OpenCode's own state dirs writable, and the project's .forge/ (other
    tasks' worktrees, logs, state.json) plus ~/.config/agentforge (API keys) hidden.
    Network stays on (the model API needs it). sandbox = "none" returns `inner` unchanged."""
    if a.get("sandbox", "bwrap") == "none":
        return inner
    bw = shutil.which(a.get("bwrap", "bwrap"))
    if not bw:
        raise RuntimeError("bubblewrap (bwrap) not found: install it (Arch/Fedora package `bubblewrap`) "
                           "or set sandbox = \"none\" for this vendor (not recommended)")
    root = Path(getattr(proj, "root", "."))
    cmd = [bw, "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--tmpfs", "/tmp"]
    hide = [root / ".forge", Path("~/.config/agentforge").expanduser()]
    hide += [Path(h).expanduser() for h in a.get("hide", [])]
    for h in hide:
        if h.exists():
            cmd += ["--tmpfs", str(h)]
    if (root / ".git").exists():   # worktree git metadata, also when the project lives under /tmp
        cmd += ["--ro-bind", str(root / ".git"), str(root / ".git")]
    rw = [Path(p).expanduser() for p in list(OPENCODE_RW_DEFAULT) + list(a.get("extra_rw", []))]
    for p in rw:
        p.mkdir(parents=True, exist_ok=True)
        cmd += ["--bind", str(p), str(p)]
    cmd += ["--bind" if writable_cwd else "--ro-bind", str(cwd), str(cwd)]
    for f in ro_files:
        cmd += ["--ro-bind", str(f), str(f)]
    return cmd + ["--chdir", str(cwd)] + inner
