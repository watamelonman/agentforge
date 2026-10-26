"""Project setup commands: init, upgrade, sync-agents."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..policy_lists import POLICY_BEGIN, render_policy_lists
from ..util import TEMPLATE, die, sh

# Files whose contents contain @NAME@ (the project name) after copying the template.
NAME_FILES = ("{name}.csproj", "forge.toml", "project.godot", "CMakeLists.txt", "conf.lua")


def cmd_init(args):
    """`forge init`: copy template/common + preset, substitute @NAME@, git init + first commit."""
    dest = Path(args.dir).resolve()
    if (dest / "forge.toml").exists():
        die(f"{dest} already has forge.toml")
    preset = TEMPLATE / "presets" / args.preset
    if not preset.exists():
        die(f"unknown preset {args.preset}; have: {[p.name for p in (TEMPLATE / 'presets').iterdir()]}")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE / "common", dest, dirs_exist_ok=True)
    shutil.copytree(preset, dest, dirs_exist_ok=True)
    if args.no_sample:
        _drop_samples(dest)
    _substitute_name(dest)
    for f in list((dest / "tools").glob("*.sh")) + list((dest / "gates").glob("*")):
        f.chmod(0o755)
    if args.spec:
        shutil.copy(args.spec, dest / "spec" / "SPEC.md")
    for f in (dest / ".claude" / "hooks").glob("*.sh"):
        f.chmod(0o755)
    _ensure_gitignore(dest)
    render_policy_lists(dest)
    _first_commit(dest)
    print(f"Initialized {dest} (preset {args.preset}).\nNext: edit spec/SPEC.md, then `forge -C {dest} plan`.")


def _drop_samples(dest):
    # Sample code only proves the gates on day one; real projects usually start clean.
    manifest = dest / ".forge-samples"
    if not manifest.exists():
        return
    for line in manifest.read_text().splitlines():
        rel = line.strip()
        if rel and not rel.startswith("#"):
            (dest / rel).unlink(missing_ok=True)
    manifest.unlink()


def _substitute_name(dest):
    """@NAME@ -> the project directory's name, in file names and in NAME_FILES."""
    for f in list(dest.rglob("*@NAME@*")):
        f.rename(f.with_name(f.name.replace("@NAME@", dest.name)))
    for name in NAME_FILES:
        f = dest / name.format(name=dest.name)
        if f.exists():
            f.write_text(f.read_text().replace("@NAME@", dest.name))


def _ensure_gitignore(dest):
    gi = dest / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    for l in (".forge/", "build/"):
        if l not in lines:
            lines.append(l)
    gi.write_text("\n".join(lines) + "\n")


def _first_commit(dest):
    if not (dest / ".git").exists():
        sh(["git", "init", "-q", "-b", "main", str(dest)])
    sh(["git", "-C", str(dest), "add", "-A"])
    sh(["git", "-C", str(dest), "-c", "user.name=forge", "-c", "user.email=forge@localhost",
        "commit", "-q", "-m", "forge init"], check=False)


def cmd_upgrade(proj, args):
    """`forge upgrade`: add files newer forge versions expect to an existing project.

    Today: .forge-samples (from the preset, listing only sample files still present) and the
    generated AGENTS.md/.claude policy lists. Never overwrites an existing .forge-samples.
    Leaves changes uncommitted for the human to review and commit."""
    preset = TEMPLATE / "presets" / args.preset
    if not preset.exists():
        die(f"unknown preset {args.preset}")
    changed = []
    src = preset / ".forge-samples"
    dst = proj.root / ".forge-samples"
    if src.exists() and not dst.exists():
        keep = [l for l in src.read_text().splitlines()
                if not l.strip() or l.startswith("#") or (proj.root / l.strip()).exists()]
        dst.write_text("\n".join(keep) + "\n")
        changed.append(".forge-samples")
    agents = proj.root / "AGENTS.md"
    if agents.exists() and POLICY_BEGIN in agents.read_text():
        if render_policy_lists(proj.root):
            changed.append("AGENTS.md/.claude/settings.json")
    elif agents.exists():
        print("note: AGENTS.md has no forge:policy-lists markers; add them (see docs/PRESETS.md) "
              "or run the project's apply script, then `forge sync-agents`.")
    print(("updated: " + ", ".join(changed) + "\nReview with `git diff`, then commit.") if changed
          else "Nothing to upgrade.")


def cmd_sync_agents(proj, args):
    """`forge sync-agents`: regenerate AGENTS.md lists and .claude Edit/Write deny rules from forge.toml."""
    changed = render_policy_lists(proj.root)
    print("AGENTS.md / .claude/settings.json updated from forge.toml [policy]; commit them."
          if changed else "AGENTS.md and .claude/settings.json already in sync.")
