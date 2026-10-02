#!/bin/sh
# Start the Codex CLI TUI so agent-link can tell which thread this pane shows.
#
# Codex records the pane-to-thread link only in the TUI's own session log, which it writes
# when started with CODEX_TUI_RECORD_SESSION=1 and CODEX_TUI_SESSION_LOG_PATH. Without it the
# pane is listed but not addressable. Usage: integrations/codex-tui.sh [codex arguments]
#
# The log holds the text you type into Codex; it is kept private (directory 0700, file 0600).

set -eu
dir="${XDG_STATE_HOME:-$HOME/.local/state}/agent-link/codex-tui"
mkdir -p "$dir"
chmod 700 "$dir"
pane="$(printf '%s' "${TMUX_PANE:-nopane}" | tr -cd 'A-Za-z0-9')"
CODEX_TUI_RECORD_SESSION=1
CODEX_TUI_SESSION_LOG_PATH="$dir/$pane-$(date +%Y%m%dT%H%M%S)-$$.jsonl"
export CODEX_TUI_RECORD_SESSION CODEX_TUI_SESSION_LOG_PATH
exec codex "$@"
