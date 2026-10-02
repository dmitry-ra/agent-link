# Claude Code adapter

Verified with Claude Code 2.1.285 on Linux. All formats below are internal to Claude Code and
may change; `agent-link doctor` checks them.

## Discovery

Claude Code keeps one file per live session in `<config>/sessions/<pid>.json`, where `<config>`
is `$CLAUDE_CONFIG_DIR` or `~/.claude`. Fields used: `pid`, `sessionId`, `cwd`, `tmux`
(`<session>:@<window id>.%<pane id>`), `messagingSocketPath`, `status` (`busy`, `idle`, ...),
`kind` (`interactive`), `name`, `version`. Files `<pid>.*.key` next to them hold secrets and are
never read.

A session is live when its pid is running. Its address is the name of the tmux session whose
pane holds its pid, found by process ancestry. The `tmux` field is only a fallback: it is written
at start and its pane id does not say which tmux server it belongs to. `whoami` walks the ancestors of the calling process until one is a registered pid, which
is the case for any command a Claude Code session runs.

## Messages

Each interactive session listens on a unix socket (`messagingSocketPath`). agent-link writes one
JSON line `{"type": "user", "msg_id": ..., "message": {"role": "user", "content": ...}, "from":
"uds:<reply socket>"}`. The inbox replies only on failure (held, dropped, refused); no receipt
within 2 s means delivered. Limits observed: about 1 MiB per line, a burst bucket of ~30
messages, identical consecutive messages from one sender dropped.

A message starts a turn when the session is idle, or is read between tool calls when busy. In
the transcript it appears as a `queue-operation` record with `operation: enqueue` and the text.

## Conversation and answers

The transcript is `<config>/projects/<escaped cwd>/<sessionId>.jsonl`, found by globbing the
session id. `read` shows user and assistant text, tool calls by name, and queued inbox
messages. `ask` looks for the message id in the transcript and returns the last assistant text
up to the first `stop_reason: end_turn` after it.

## Limits

- Subagents of a Claude Code session run inside its process and have no inbox: not listed.
- A non-interactive run (`claude -p`) has no inbox.
