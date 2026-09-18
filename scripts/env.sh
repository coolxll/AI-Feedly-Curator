#!/usr/bin/env bash
# Project-level venv selector for shared Win/WSL repo.
# AGENTS.md: Windows -> .venv-win, WSL/Linux -> .venv-wsl
# Works in both Windows Git Bash (MINGW/MSYS/CYGWIN) and WSL/Linux.
#
# Usage:
#   source scripts/env.sh              # export UV_PROJECT_ENVIRONMENT into current shell, then use `uv run` normally
#   bash scripts/env.sh python -V      # wrapper mode: sets env and execs `uv run "$@"`
#   bash scripts/env.sh python article_analyzer.py --refresh

# Only enable strict mode when executed directly, not when sourced into an interactive shell
is_sourced=0
if [[ "${BASH_SOURCE[0]:-}" != "${0}" ]]; then
  is_sourced=1
else
  set -euo pipefail
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-${0}}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  MINGW*|MSYS*|CYGWIN*)
    VENV=".venv-win"
    ;;
  *)
    # WSL / Linux: prefer .venv-wsl if present, else fallback to .venv if valid
    if [ -d "$ROOT/.venv-wsl" ]; then
      VENV=".venv-wsl"
    elif [ -f "$ROOT/.venv/bin/python" ]; then
      VENV=".venv"
    else
      VENV=".venv-wsl"
    fi
    ;;
esac

export UV_PROJECT_ENVIRONMENT="$VENV"

if [ "$is_sourced" -eq 1 ]; then
  echo "UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT (exported for current shell)"
  feedly_tui() {
    uv run python "$ROOT/feedly_tui.py" "$@"
  }
  alias feedly_tui="uv run python feedly_tui.py" 2>/dev/null || true
else
  if [ $# -gt 0 ]; then
    exec uv run "$@"
  else
    echo "UV_PROJECT_ENVIRONMENT=$UV_PROJECT_ENVIRONMENT"
    echo "hint: source scripts/env.sh        # export into current shell"
    echo "      bash scripts/env.sh python -V  # wrapper mode"
  fi
fi
