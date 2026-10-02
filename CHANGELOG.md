# Changelog

## 0.1.0 - unreleased

First version.

- Commands: `whoami`, `list`, `read`, `send`, `ask`, `status`, `doctor`, `guide`, `rpc`.
- Adapters: Claude Code (session registry, inbox socket, transcript) and Codex CLI (thread
  rollouts, `codex queue`, pane-to-thread binding through the TUI session log, including after
  `/new` and `resume`; subagents).
- Addresses from tmux session names; program session names and `kind#id` also accepted.
- Message envelope with computed sender, conversation id, hop limit, and two reply modes
  (`send` back, or `WAITING` for `ask`).
- Protocol 1: every operation is a JSON request and response (`agent-link rpc`).
- MIT license.
