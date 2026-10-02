# agent-link

A small command-line tool that lets AI coding agents on one machine find each other, read each
other's conversations, send messages and wait for answers.

![Claude Code and Codex CLI talking through agent-link](docs/demo.gif)

Left, Claude Code asks Codex CLI (right) to review a file with `agent-link ask` and waits for the
answer. It fixes the bug Codex found and tells Codex what changed with `agent-link send`.

```
$ agent-link list
project-1        claude  idle               project-3a
codex-1          codex   busy               Fix flaky test
codex-1/helper   codex   idle               -
$ agent-link ask codex-1 "Which test are you fixing?"
ok: codex-1 (instance 9f3a1c2e-...) message m-1a2b3c4d
tests/test_cache.py::test_expiry
```

Supported today: **Claude Code** and **Codex CLI** running in **tmux** on **Linux**. Built to
grow: one adapter per agent program, one provider per terminal multiplexer, and (planned)
transports to agents on other machines or virtual machines.

Agents using the tool: read [AGENTS.md](AGENTS.md), or run `agent-link guide`.

## Unofficial

agent-link is an independent project. It is not affiliated with, endorsed by or supported by
Anthropic or OpenAI. It works by reading files and using local interfaces that Claude Code and
Codex CLI keep for themselves; none of them is a documented public API, and any release of
those programs may change them. `agent-link doctor` checks what it relies on and says what
changed.

## Requirements

- Linux (process information comes from `/proc` and `ps`)
- Python 3.11 or newer, standard library only
- tmux, with the agents running in tmux sessions (the session name is the agent's address)
- the agent programs themselves:

| program | versions checked | notes |
|---|---|---|
| Claude Code | 2.1.284, 2.1.285, 2.1.287 | messages need the session's inbox socket (`messagingSocketPath` in its session registry); `agent-link doctor` shows whether your version has it |
| Codex CLI | 0.160.0 | start the terminal UI with `integrations/codex-tui.sh` (or set the two variables it sets) so its pane can be addressed |

## Install

From a clone:

```
./install.sh
```

links `bin/agent-link` into `~/.local/bin` and the skill files into `~/.claude/skills` and
`~/.codex/skills` when those directories exist. It is safe to run again and only replaces links
that point into this repository.

Or as a package (the program only; skills are linked by `install.sh`):

```
pipx install git+https://github.com/dmitry-ra/agent-link
```

Without installing anything: `python3 bin/agent-link ...` from the clone.

Then check that your agent programs look as expected:

```
agent-link doctor
```

## Let the agents run it

Agents call `agent-link` through their shell tool, so each agent program has to be allowed to run
it without asking every time.

- **Claude Code**: allow the command in `~/.claude/settings.json` (or a project's
  `.claude/settings.json`). Without this, Claude asks before every call.

  ```json
  { "permissions": { "allow": ["Bash(agent-link:*)"] } }
  ```

- **Codex CLI**: add a rule to a rules file such as `~/.codex/rules/default.rules`, then restart
  Codex (it reads rules at start):

  ```
  prefix_rule(pattern=["agent-link"], decision="allow")
  ```

  This is required, not only convenient. agent-link reads other processes and their sockets,
  which Codex's sandbox hides: run inside the sandbox, it finds no agents at all (`list` prints
  nothing, `send` answers "known addresses: none"). A command allowed by a rule runs outside the
  sandbox.

A new Codex session can be addressed only after its first message: Codex writes the thread to
disk then. Start it with `integrations/codex-tui.sh` (see Requirements) and type anything first.

## Configuration

Optional: `~/.config/agent-link/config.toml` (or `$AGENT_LINK_CONFIG`) with `node` (this
machine's name in addresses), `hop_limit` and `[aliases]`. See `agentlink/config.py`.

## Security model

- **Trust boundary: one user account.** agent-link only sees and talks to agents of the user it
  runs as. Any process of that user can already write to these agents' inboxes; agent-link does
  not add a new way in, it makes the existing one convenient and labelled.
- **Messages are not instructions from the user.** Every message carries a header saying it
  comes from another agent, and the sender address is computed by agent-link, not typed by the
  sending model. Whether an agent acts on a peer's request is decided by that agent's own rules.
- **Prompt injection still applies.** A message from another agent is untrusted text, like a web
  page. Do not let agents act on it beyond what their rules allow.
- **Loops are bounded.** A hop counter travels with each conversation; past the limit (default
  10) messages are refused.
- **Secrets.** agent-link never reads Claude Code's `*.key` files. The Codex session log it relies
  on contains what you type into Codex; `integrations/codex-tui.sh` keeps it in a private
  directory.

Report a vulnerability as described in [SECURITY.md](SECURITY.md).

## Develop

```
python3 -m unittest discover -s tests -t .   # unit and conformance tests, offline
python3 tools/mutate.py                      # each core mechanism broken in turn; tests must fail
```

CI runs the same on Python 3.11-3.13, plus pyflakes, shellcheck and a wheel install. Testing
plan: [docs/testing.md](docs/testing.md). Supporting another agent program:
[docs/adding-an-adapter.md](docs/adding-an-adapter.md). Contributing:
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT, see [LICENSE](LICENSE).
