---
name: agent-link
description: Find, read and message other AI agents on this machine (Claude Code sessions, Codex CLI, other Pi sessions) and get their answers. Use when you need something from another agent, when a message starting with "[agent-link]" arrives, or when asked which agents are running.
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

A reply by send looks like this:

```
agent-link send <sender> --conversation <c-...> --hops <n> - <<'EOF'
your answer
EOF
```

Pi specifics:
- Your address is your tmux session name; `agent-link whoami` shows it. If it says the agent-link
  extension is not loaded, others cannot reach you: tell your user.
- `agent-link ask` blocks your bash tool until the answer comes (up to `--timeout`, default 600 s);
  give a smaller `--timeout` for quick questions.
