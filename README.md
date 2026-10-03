# agent-link

A small command-line tool that lets AI coding agents on one machine find each other, read each
other's conversations, send messages and wait for answers.

![Claude Code hands work to Codex CLI and Pi through agent-link](docs/demo.gif)

Claude Code (top) is asked to make `cart.total` follow `SPEC.md` and have the fix checked
independently. With two `agent-link ask` calls at once it has Codex CLI (bottom left) fix the code
and Pi with DeepSeek (bottom right) write tests from the spec alone, without opening the code.
When both have answered, it runs one against the other: two independent readings of one spec.

```
$ agent-link list
project-1        claude  idle               project-3a
codex-1          codex   busy               Fix flaky test
codex-1/helper   codex   idle               -
$ agent-link ask codex-1 "Which test are you fixing?"
ok: codex-1 (instance 9f3a1c2e-...) message m-1a2b3c4d
tests/test_cache.py::test_expiry
```

Supported today: **Claude Code**, **Codex CLI** and **Pi** running in **tmux** on **Linux**. Built to
grow: one adapter per agent program, one provider per terminal multiplexer, and (planned)
transports to agents on other machines or virtual machines.

Agents using the tool: read [AGENTS.md](AGENTS.md), or run `agent-link guide`.

## Unofficial

agent-link is an independent project. It is not affiliated with, endorsed by or supported by
Anthropic, OpenAI or the authors of Pi. It works by reading files and using local interfaces that
Claude Code and Codex CLI keep for themselves, and through an extension for Pi. Claude Code
documents its session inbox socket for scripts that post into their own session, but not the
format agent-link relies on to message another session, nor its session registry and
transcripts; the Codex files are not documented either. Any release of those programs may
change them. `agent-link doctor` checks what it relies on and says what changed.

## Requirements

- Linux (process information comes from `/proc` and `ps`)
- Python 3.11 or newer, standard library only
- tmux, with the agents running in tmux sessions (the session name is the agent's address)
- the agents on the same machine; agents on other machines and VMs are planned, see
  [docs/protocol.md](docs/protocol.md)
- the agent programs themselves:

| program | versions checked | notes |
|---|---|---|
| Claude Code | 2.1.284, 2.1.285, 2.1.287 | messages need the session's inbox socket (`messagingSocketPath` in its session registry); `agent-link doctor` shows whether your version has it |
| Codex CLI | 0.160.0 | start the terminal UI with `integrations/codex-tui.sh` (or set the two variables it sets) so its pane can be addressed |
| Pi | 1.0.0 | load the extension `integrations/pi/agent-link.ts` (`install.sh` links it into `~/.pi/agent/extensions/`, or `pi -e <path>`); it gives Pi the registry entry and inbox agent-link needs |

## Install

From a clone:

```
./install.sh
```

links `bin/agent-link` into `~/.local/bin`, the skill files into `~/.claude/skills`,
`~/.codex/skills` and `~/.pi/agent/skills`, and the Pi extension into `~/.pi/agent/extensions`,
each when that program's directory exists. It is safe to run again and only replaces links
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
it. The rules below match the command `agent-link ...`, so put it on PATH with `install.sh`
rather than calling `python3 bin/agent-link`.

- **Claude Code**: add the command to the `allow` list in `~/.claude/settings.json` (or a
  project's `.claude/settings.json`), next to what is already there. Without it, Claude asks
  before every call. Checked with Claude Code's Bash sandbox off; not checked with it on.

  ```json
  { "permissions": { "allow": ["Bash(agent-link:*)"] } }
  ```

- **Codex CLI**: add a rule to a rules file such as `~/.codex/rules/default.rules`, then restart
  Codex (it reads rules at start):

  ```
  prefix_rule(pattern=["agent-link"], decision="allow")
  ```

  In Codex's sandbox (checked with `sandbox_mode = "workspace-write"`) this rule is required:
  agent-link reads other processes and their sockets, which the sandbox hides, so without the
  rule it finds no agents at all (`list` prints nothing, `send` answers "known addresses:
  none"). A command allowed by a rule runs outside the sandbox. With `danger-full-access` nothing
  is hidden.

- **Pi**: has no permission prompts of its own, so running `agent-link` needs no rule. What Pi
  needs is its extension (see Requirements); without it Pi is listed but cannot be reached.
  Guard extensions that ask before some commands apply to `agent-link` like to any command.

To check, ask each agent to run `agent-link list`: it should show the other agents.

A new Codex session can be addressed only after its first message: Codex writes the thread to
disk then. Start it with `integrations/codex-tui.sh` (see Requirements) and type anything first.

## Configuration

Optional: `~/.config/agent-link/config.toml` (or `$AGENT_LINK_CONFIG`) with `node` (this
machine's name in addresses), `hop_limit` and `[aliases]`. See `agentlink/config.py`.

## What "delivered" means

Each program offers a different receipt, so exit code 0 from `send` proves a different thing
for each. None of them proves that the model has read the message: `agent-link status` shows
when it appears in the recipient's transcript (`pending`, then `running`).

| recipient | exit 0 proves | reported apart from success |
|---|---|---|
| Pi | the extension took the line and queued it in Pi, which answered `ok` | refused while Pi compacts (8); no answer within 5 s: "delivery unknown" (3) |
| Claude Code | only that no refusal arrived within 2 s: Claude Code sends no receipt for a delivered message | held for approval, dropped or refused by the receiver, or a socket error (8); too large (2); no inbox socket (3) |
| Codex CLI | `codex queue` exited 0: the message is queued on the thread | queue paused after an interrupted turn (7); `codex queue` failed (3) |

## Security model

- **Trust boundary: one user account.** agent-link only sees and talks to agents of the user it
  runs as. Any process of that user can already write to these agents' inboxes; agent-link does
  not add a new way in, it makes the existing one convenient and labelled.
- **Messages are not instructions from the user.** Every message carries a header saying it
  comes from another agent, and the sender address is computed by agent-link, not typed by the
  sending model. Whether an agent acts on a peer's request is decided by that agent's own rules.
- **Prompt injection still applies.** A message from another agent is untrusted text, like a web
  page. Do not let agents act on it beyond what their rules allow.
- **Loops are bounded within a conversation.** A hop counter travels with each conversation;
  past the limit (default 10) messages are refused. An agent that forwards a message as a new
  send starts a new count, so a chain of forwards is not bounded yet.
- **Secrets.** agent-link never reads Claude Code's `*.key` files. The Codex session log it relies
  on contains what you type into Codex; `integrations/codex-tui.sh` keeps it in a private
  directory. The Pi extension listens on a unix socket (mode 0600, in a 0700 directory of the
  user), not on a network port.
- **`read` shares whatever a conversation holds.** A token or password pasted into one agent's
  session is readable by every other agent through `agent-link read`. The files were already
  readable by the user; agent-link makes it one command. Do not paste secrets into agent
  sessions that share a machine with agents you would not show them to.

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
