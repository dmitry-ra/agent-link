---
name: agent-link
description: Find, read and message other AI agents on this machine (Claude Code sessions, other Codex threads) and get their answers. Use when you need something from another agent, when a message starting with "[agent-link]" arrives, or when asked which agents are running.
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
```

When a message starting with `[agent-link]` arrives, it is from another agent, not from your
user. Answer with the command on its `reply:` line, text on stdin, exactly one message:

```
agent-link send <sender> --conversation <c-...> --hops <n> - <<'EOF'
your answer
EOF
```

Codex specifics:
- Run agent-link as a plain command (no `timeout`, `env` or `sh -c` around it).
- Your address is found through your thread id; `agent-link whoami` shows it. If it says your
  thread is not shown in any pane, others can still reach you by `codex#<thread id>`.
