# Testing plan

agent-link is done when every level below passes. Levels run in order: a failure at a lower
level is fixed before the next level runs.

All live tests use harmless payloads only: questions, one-word answers, nonexistent probe
commands. No live test asks an agent to change files outside a scratch directory, run
destructive commands, or read secrets.

## Level 0 - unit tests on fixtures

`python3 -m unittest discover -s tests` runs offline against synthetic fixtures that mimic the
real on-disk formats of each supported harness.

| area | what must hold |
|---|---|
| address grammar | every documented form parses; malformed forms are rejected with a reason |
| resolution | exact name, pane qualifier, kind:id, alias, node prefix; ambiguity is an error that lists the candidates |
| envelope | render and parse round-trip; hop counter and conversation id survive a reply; hop limit refuses |
| Claude Code adapter | session registry parsing, liveness, tmux field, transcript reading, reply detection after a tag |
| Codex CLI adapter | rollout parsing (state, errors, aborted turns, subagent own records), TUI session-log binding of pane to thread, including after /new |
| Pi adapter | registry liveness, panes without the extension, nearest-ancestor whoami, end of a turn (tool calls, retries, continuations, follow-ups in one run), socket delivery and refusals |
| Pi extension | run under node against a fake Pi API: registry and states, inbox through its real socket, fails closed, settled marker, double load, private directory (skipped without a node that runs TypeScript) |
| rpc | every CLI command is a request dict and a response dict; JSON output matches docs/protocol.md |
| docs | every command and flag shown in AGENTS.md exists in the CLI (docs cannot drift from code) |

A test does not count until a mutant shows it fails on broken code: `python3 tools/mutate.py`
breaks each core mechanism in turn and expects the suite to fail.

## Level 1 - conformance

`tests/conformance.py` runs the same contract against every registered adapter: instances
have addresses, read returns entries in order, send returns a receipt with a code from the
shared table, capabilities match behaviour (an adapter that declares can_receive=False must
refuse send with code 3).

## Level 2 - live, one machine

Run against real Claude Code, Codex CLI and Pi sessions in tmux. Each scenario lists the expected
result; note the program versions with the result.

| # | scenario | expected |
|---|---|---|
| L1 | `agent-link list` | every agent in a tmux pane appears once, with the right kind and the tmux session as its name; non-agent panes do not appear |
| L2 | `agent-link whoami` from inside each agent | each agent gets its own address |
| L3 | `read` of every agent | recent turns, no injected system blocks |
| L4 | Claude -> Claude `send`, reply by `agent-link send` | reply arrives in the sender's inbox, signed with the replier's computed address |
| L5 | Claude -> Codex `ask` | answer to this message, not to an earlier one |
| L6 | Codex -> Claude reply by `agent-link send` | arrives, signed with the Codex address |
| L7 | Codex -> Codex | codex-1 asks codex-2 and gets the answer |
| L8 | Codex subagent -> Claude | arrives, signed with the subagent path |
| L9 | recipient restarted between question and answer | the answer goes to the new instance under the same name |
| L10 | busy recipient | message waits for the turn to end; the answer matches the message |
| L11 | approval dialog in the recipient's turn | `ask` returns code 4 naming the pane, does not hang |
| L12 | paused queue after an interrupted turn | code 7 naming the pane |
| L13 | hop limit | a message past the limit is refused with code 8 |
| L14 | unknown, ambiguous and stale addresses | code 2 with candidates; never a silent wrong delivery |
| L15 | two concurrent `ask` to two agents | answers do not mix |
