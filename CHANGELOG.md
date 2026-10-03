# Changelog

## 0.1.0 - unreleased

First version.

- Commands: `whoami`, `list`, `read`, `send`, `ask`, `status`, `doctor`, `guide`, `rpc`.
- Adapters: Claude Code (session registry, inbox socket, transcript) and Codex CLI (thread
  rollouts, `codex queue`, pane-to-thread binding through the TUI session log, including after
  `/new` and `resume`; subagents).
- Adapter for Pi 1.0.0 with its extension (`integrations/pi/agent-link.ts`): registry entry and
  unix-socket inbox per Pi process, messages as `agent-link` custom messages queued behind the
  current work, and a settled marker in the session file so `ask` waits out retries and
  continuations. `install.sh` links the extension and a Pi skill.
- Addresses from tmux session names, across the tmux servers in the user's tmux socket
  directory; agents whose session address would collide are named `kind#id`. Program session
  names and `kind#id` are also accepted.
- Message envelope with computed sender, conversation id, hop limit, and two reply modes
  (`send` back, or `WAITING` for `ask`). The body is closed by an end line carrying the message
  id, and body lines that could pass for a header are escaped with `>`, so a message cannot
  carry a forged second header (reported on The Colony). `hops` below 0 or not a whole number
  is refused with code 2 instead of rendering a header that cannot be read back.
- Protocol 1: every operation is a JSON request and response (`agent-link rpc`).
- MIT license.
