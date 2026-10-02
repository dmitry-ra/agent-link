# agent-link

A small command-line tool that lets AI coding agents on one machine find each other, read each
other's conversations, send messages and wait for answers. Supported: Claude Code and Codex
CLI, in tmux. Designed to grow: one adapter per agent program, one provider per terminal
multiplexer, and (planned) transports to agents on other machines or virtual machines.

Agents: read [AGENTS.md](AGENTS.md).

## Install

```
./install.sh
```

Links `bin/agent-link` into `~/.local/bin` and the skill files into `~/.claude/skills` and
`~/.codex/skills` when those directories exist. Safe to run again; never overwrites a file it did
not create. Without installing: `python3 bin/agent-link ...`.

Start Codex terminals with `integrations/codex-tui.sh` so they can be addressed.

## Configuration

Optional, machine-specific, never in this repository: `~/.config/agent-link/config.toml`
(`node` name, `hop_limit`, `[aliases]`). See `agentlink/config.py`.

## Develop

```
python3 -m unittest discover -s tests     # unit and conformance tests
python3 tools/mutate.py                   # each core mechanism broken in turn; tests must fail
```

Testing plan: [docs/testing.md](docs/testing.md). Adding an agent program:
[docs/adding-an-adapter.md](docs/adding-an-adapter.md).

Repository content is English and ASCII only.
