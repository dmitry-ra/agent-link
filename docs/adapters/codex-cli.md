# Codex CLI adapter

Verified with Codex CLI 0.160 on Linux. All formats below are internal to Codex and may change;
`agent-link doctor` checks them.

## How Codex is laid out

- Terminal UIs (TUIs) are clients of one shared `app-server` daemon. The daemon holds the
  threads, runs the model turns, and also runs hooks and the shell commands Codex executes.
- Threads are stored as `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<start time>-<thread id>.jsonl`
  (`$CODEX_HOME` defaults to `~/.codex`); names in `$CODEX_HOME/session_index.jsonl`.
- A new TUI already has a thread in the daemon, but the rollout file is written only with the
  first message, so an empty TUI cannot be addressed yet.

## Which thread does a pane show

Nothing in the thread records which terminal shows it, and hooks or commands cannot tell either:
they run in the daemon, whose `TMUX_PANE` belongs to whatever started the daemon. The one record
that does is the TUI's own session log, written when the TUI starts with

```
CODEX_TUI_RECORD_SESSION=1
CODEX_TUI_SESSION_LOG_PATH=<file>
```

`integrations/codex-tui.sh` sets both. The log has a `session_start` or `new_session` record
(after `/new`) with a timestamp, and an `op` record for every typed turn carrying
`client_user_message_id`, which the rollout stores as `client_id`. agent-link reads the log path
from the TUI process environment and binds the pane to the thread holding the latest client id,
or, before any typed turn in that thread, to the rollout whose `session_meta.timestamp` matches
the marker within 3 s.

The log contains what you type into Codex; the wrapper keeps it private (0700 directory).

## Messages

`codex queue --thread <id> --message <text>` hands the message to the daemon; a busy thread runs
it after the current turn. Shell commands Codex runs get `CODEX_THREAD_ID`, which is how
`whoami` works from inside Codex.

## Answers and states

`ask` finds the user message carrying the message id in the rollout and returns the last
assistant message up to `task_complete`. A `task_complete` with an `error` field (for example
"Selected model is at capacity") or a `turn_aborted` is code 6.

Not in the rollout, only on the pane screen:
- an approval dialog ("Would you like to run ...") - code 4, pane named;
- a paused queue after an interrupted turn ("Conversation interrupted") - code 7. Queued messages
  run only after someone types in the pane; type something neutral, because "continue" makes
  Codex retry the interrupted step.

## Subagents

A subagent has its own rollout whose `session_meta.source.subagent.thread_spawn` names the
parent thread and the agent path (`/root/<name>`); its file starts with a copy of the parent's
history, and its own work begins at the first `inter_agent_communication_metadata` record.
Subagents are listed under their parent's address as `<parent>/<name>`.
