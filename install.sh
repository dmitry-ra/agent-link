#!/bin/sh
# Link agent-link into the user's PATH and into the skill directories of supported agents.
# Safe to run again. Never replaces a file or directory it did not create (only its own links).

set -eu
repo="$(cd "$(dirname "$0")" && pwd -P)"

link() {
    src="$1"
    dst="$2"
    if [ -L "$dst" ]; then
        ln -sfn "$src" "$dst"
        echo "updated  $dst -> $src"
    elif [ -e "$dst" ]; then
        echo "skipped  $dst exists and is not a link; move it away to install" >&2
        return 0
    else
        mkdir -p "$(dirname "$dst")"
        ln -s "$src" "$dst"
        echo "linked   $dst -> $src"
    fi
}

link "$repo/bin/agent-link" "$HOME/.local/bin/agent-link"
[ -d "$HOME/.claude" ] && link "$repo/skills/claude-code/agent-link" "$HOME/.claude/skills/agent-link"
[ -d "${CODEX_HOME:-$HOME/.codex}" ] && link "$repo/skills/codex/agent-link" "${CODEX_HOME:-$HOME/.codex}/skills/agent-link"

case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) echo "note: $HOME/.local/bin is not on PATH; add it or call $repo/bin/agent-link" >&2 ;;
esac
echo "check: agent-link doctor"
