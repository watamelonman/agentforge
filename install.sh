#!/usr/bin/env bash
# AgentForge installer for Arch Linux and Fedora. Idempotent. Never touches credentials.
# Usage: ./install.sh [--with-csharp] [--with-raylib] [--no-agents] [--yes]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
CSHARP=0 RAYLIB=0 AGENTS=1 YES=""
for a in "$@"; do
  case $a in
    --with-csharp) CSHARP=1 ;; --with-raylib) RAYLIB=1 ;; --no-agents) AGENTS=0 ;;
    --yes|-y) YES=1 ;; -h|--help) sed -n 2,3p "$0"; exit 0 ;; *) echo "unknown option $a"; exit 2 ;;
  esac
done
# shellcheck source=/dev/null
. /etc/os-release
distro="${ID:-unknown} ${ID_LIKE:-}"
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

base_arch=(git tmux jq python python-pip python-pipx nodejs npm shellcheck godot)
base_fedora=(git tmux jq python3 python3-pip pipx nodejs npm ShellCheck godot)
if [[ $distro == *arch* ]]; then
  pkgs=("${base_arch[@]}")
  ((CSHARP)) && pkgs+=(dotnet-sdk-8.0)      # Godot .NET: install `godot-mono` (extra/AUR) or official binary
  ((RAYLIB)) && pkgs+=(cmake gcc clang ninja raylib lua)
  say "pacman: ${pkgs[*]}"
  sudo pacman -S --needed ${YES:+--noconfirm} "${pkgs[@]}"
elif [[ $distro == *fedora* ]]; then
  pkgs=("${base_fedora[@]}")
  ((CSHARP)) && pkgs+=(dotnet-sdk-8.0)
  ((RAYLIB)) && pkgs+=(cmake gcc gcc-c++ clang clang-tools-extra ninja-build raylib-devel lua-devel libasan libubsan)
  say "dnf: ${pkgs[*]}"
  sudo dnf install ${YES:+-y} "${pkgs[@]}"
else
  echo "Unsupported distro ($distro). Install manually: ${base_fedora[*]}"; exit 1
fi

say "gdtoolkit (gdlint/gdformat) via pipx"
pipx install 'gdtoolkit==4.*' >/dev/null 2>&1 || pipx upgrade gdtoolkit >/dev/null 2>&1 || true

mkdir -p "$HOME/.local/bin"
if ((AGENTS)); then
  if ! command -v claude >/dev/null; then
    say "Claude Code (official native installer)"
    curl -fsSL https://claude.ai/install.sh | bash
  fi
  if ! command -v codex >/dev/null; then
    say "Codex CLI (npm, user prefix ~/.local - no sudo)"
    npm config set prefix "$HOME/.local"
    npm install -g @openai/codex
  fi
fi

# forge = bin/forge (thin entry point) + the agentforge/ package beside it. The symlink keeps
# both in this checkout: bin/forge resolves its own path and imports ../agentforge, so a
# `git pull` here updates the installed forge. Never copy bin/forge on its own.
if [[ ! -f "$here/agentforge/__init__.py" ]]; then
  echo "agentforge/ package missing next to bin/forge in $here; re-clone the repo"; exit 1
fi
ln -sf "$here/bin/forge" "$HOME/.local/bin/forge"
mkdir -p "$HOME/.config/systemd/user"
cp "$here/systemd/forge-run@.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload 2>/dev/null || true
# shellcheck disable=SC2016
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'Add to your shell rc: export PATH="$HOME/.local/bin:$PATH"' ;; esac

say "Checking tools and logins (no secrets are read)"
"$here/bin/forge" doctor || true
cat <<'MSG'

If an agent shows NOT logged in, run it once interactively:
  claude auth login        # or: claude  (then /login)
  codex login              # or: codex login --device-auth  (no browser)
Then: forge init ~/games/mygame && cd ~/games/mygame && cat QUICKSTART.md
MSG
