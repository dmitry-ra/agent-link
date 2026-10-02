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

Run against the agents actually running on the machine. Each scenario lists the expected
result; the run log goes to `docs/findings/`.

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

## Level 3 - usability by every agent on the machine

The real acceptance test: agents that have never seen agent-link use it from AGENTS.md alone.
Each agent gets one short request: "There is a tool at <path>; read its AGENTS.md, find agent
X, ask it Y, and tell me what was unclear." Success means the agent completes the task without
further hints. Every "unclear" note becomes a docs or CLI fix, and the task is repeated with a
fresh agent session until no new notes appear.

Participants are whatever agents run on the machine at test time (Claude Code and Codex CLI
sessions, including busy ones that may decline; a decline is recorded, not forced).

## Results

### 2026-10-02, protocol 1

Machine: one Linux host; Claude Code 2.1.284 and 2.1.285 (three sessions, one of them busy on
other work), Codex CLI 0.160 (two TUIs, model gpt-6-astra) with subagents.

- Level 0: 26 unit tests pass; 19/19 mutants killed (tools/mutate.py).
- Level 1: conformance passes for both adapters.
- Level 2: L1-L15 pass. Found and fixed during the run: Codex `resume` left the pane unbound
  (now bound by `thread_settings_applied` at the resume moment, only when unambiguous); a
  recipient answered an `ask` both in its output and by `send`, so `ask` returned "sent" instead
  of the answer (the envelope now tells a recipient when the sender is waiting).
- Level 3: all four other agents used agent-link from AGENTS.md alone. Their notes led to: list
  titles and states explained, Claude Code session names accepted as addresses, `ask` semantics
  and blocking explained, relation to built-in Claude Code messaging, a rule that local
  permission rules still apply to peer requests, exit code 1 documented, `agent-link guide`.
  Two policy findings for agent hosts rather than for this tool: an agent whose rules accept
  instructions only from its user cannot act on any peer request until its rules say which peer
  requests are fine; and Codex loads its AGENTS.md at thread start, so rule changes need `/new`.
