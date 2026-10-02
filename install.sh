#!/bin/sh
# Link agent-link into the user's PATH and into the skill directories of supported agents.
# Safe to run again. Replaces only links that point into this repository; anything else at a
# target path (a file, a directory, a link elsewhere) is left alone and reported.

set -eu
repo="$(cd "$(dirname "$0")" && pwd -P)"

link() {
    src="$1"
    dst="$2"
    if [ -L "$dst" ]; then
        case "$(readlink "$dst")" in
            "$repo"/*)
                ln -sfn "$src" "$dst"
                echo "updated  $dst -> $src" ;;
            *)
                echo "skipped  $dst links to $(readlink "$dst"), not into this repository" >&2 ;;
        esac
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
