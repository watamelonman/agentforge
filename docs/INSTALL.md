# Installer (`install.sh`)

```
./install.sh [--with-csharp] [--with-raylib] [--no-agents] [--yes]
```
| Option | Effect |
|---|---|
| `--with-csharp` | Also installs `dotnet-sdk-8.0`. |
| `--with-raylib` | Also installs the CMake/C toolchain plus raylib and Lua dev packages. |
| `--no-agents` | Skips installing `claude`/`codex`. |
| `--yes`, `-y` | Non-interactive package manager. |

What it does, in order:
1. Detects the distro from `/etc/os-release` (`ID`/`ID_LIKE` containing `arch` or `fedora`).
   Anything else exits with a package list for manual install.
2. Installs packages:
   - **Arch** (`pacman -S --needed`): git tmux jq python python-pip python-pipx nodejs npm
     shellcheck godot [+ dotnet-sdk-8.0] [+ cmake gcc clang ninja raylib lua]
   - **Fedora** (`dnf install`): git tmux jq python3 python3-pip pipx nodejs npm ShellCheck godot
     [+ dotnet-sdk-8.0] [+ cmake gcc gcc-c++ clang clang-tools-extra ninja-build raylib-devel
     lua-devel libasan libubsan]
3. `pipx install 'gdtoolkit==4.*'` (provides gdlint and gdformat).
4. Agents, only if missing: Claude Code through the official native installer
   (`curl -fsSL https://claude.ai/install.sh | bash`); Codex with
   `npm install -g @openai/codex` using an npm prefix of `~/.local` (no sudo).
5. Symlinks `~/.local/bin/forge` to the checkout's `bin/forge` (which imports the `agentforge/`
   package next to it, so keep the checkout in place) and installs `~/.config/systemd/user/forge-run@.service`.
6. Runs `forge doctor`, which only reports login status. **The installer never reads, writes,
   or asks for API keys or tokens.** Log in yourself with `claude auth login` and `codex login`
   (add `--device-auth` on a machine without a browser).

Godot .NET isn't in the Fedora repos. On Arch it's `godot-mono`. Otherwise download the
official ".NET" Linux build and set `[engine] godot_bin` to its path. Flatpak works for the
editor, but headless gates are simpler with a native binary.

## Unattended runs (systemd user service)
```
systemctl --user start  "forge-run@$(systemd-escape -p ~/games/mygame).service"
journalctl --user -fu   "forge-run@$(systemd-escape -p ~/games/mygame).service"
```
It runs `forge -C <path> run --parallel 2 --audit` once. To keep it going past logout, enable
lingering with `loginctl enable-linger $USER`.
