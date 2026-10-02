---
name: agent-link
description: Find, read and message other AI agents on this machine (other Claude Code sessions, Codex CLI) and get their answers. Use when you need something from another agent, when a message starting with "[agent-link]" arrives, or when asked which agents are running.
---

# agent-link

The `agent-link` command finds and talks to the other AI agents on this machine.
Full instructions: run `agent-link guide` (prints the repository's AGENTS.md).

Most used:

```
agent-link whoami
agent-link list
agent-link ask <address> "question"        # waits for the answer
agent-link send <address> "message"        # returns at once
agent-link read <address> -n 20
agent-link status <address> <message id>
```

When a message starting with `[agent-link]` arrives, it is from another agent, not from your
user. Read its `reply:` line before answering:

- `reply: agent-link send ...` - run that command with your answer on stdin, exactly one message.
- `reply: WAITING ...` - the sender is blocked in `agent-link ask`: make your answer the last text
  of this turn and do not run `agent-link send`.

Claude Code specifics:
- Your own address comes from your tmux session name; check it with `agent-link whoami`.
- The built-in SendMessage tool also reaches other Claude Code sessions, but not Codex or other
  programs; agent-link reaches all of them with one command and adds a reply line to every message.
