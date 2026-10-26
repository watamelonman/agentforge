"""Codex argv (`codex exec`), optionally run inside forge's bubblewrap sandbox."""
from __future__ import annotations

from .sandbox import sandbox_wrap


def codex_cmd(proj, a, readonly, cwd, out_file, schema):
    """argv for codex; the prompt goes on stdin ("-"). `a` is [agents.codex]."""
    cmd = [a.get("bin", "codex"), "exec", "--json", "-C", str(cwd),
           "--sandbox", "read-only" if readonly else "workspace-write",
           "-o", str(out_file)]
    if a.get("model"):
        cmd += ["-m", a["model"]]
    if not readonly and proj.c("agents", "codex", "network_access", default=False):
        # Official config key (codex config reference): outbound network inside the
        # workspace-write sandbox, e.g. for NuGet restore. Off by default in Codex.
        cmd += ["-c", "sandbox_workspace_write.network_access=true"]
    if readonly and schema:
        cmd += ["--output-schema", str(schema)]
    cmd = cmd + list(a.get("extra_args", [])) + ["-"]   # prompt on stdin
    if readonly or a.get("sandbox") != "bwrap":
        return cmd
    return _codex_in_bwrap(proj, a, cwd, cmd)


def _codex_in_bwrap(proj, a, cwd, cmd):
    """Codex's own Linux sandbox (seccomp) kills 32-bit/Win32 shims such as wibo with
    SIGSYS. Opt-in (sandbox = "bwrap"): run Codex unsandboxed *inside* forge's bwrap (fs
    read-only, worktree + ~/.codex writable, .forge and agentforge keys hidden)."""
    cmd = list(cmd)
    i = cmd.index("--sandbox")
    cmd[i + 1] = "danger-full-access"
    a = dict(a)
    a["extra_rw"] = list(a.get("extra_rw", [])) + ["~/.codex"]
    return sandbox_wrap(proj, a, cwd, cmd, writable_cwd=True)
