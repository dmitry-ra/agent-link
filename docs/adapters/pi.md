# Pi adapter

Verified with Pi 1.0.0 (`@earendil-works/pi-coding-agent`) on Linux. Pi keeps no registry of
running sessions and no inbox of its own, so this adapter has two halves: an extension that
runs inside Pi (`integrations/pi/agent-link.ts`) and the adapter module
(`agentlink/adapters/pi.py`). The extension uses only Pi's documented extension API; the session
file format is documented by Pi too (`docs/session-format.md`), but it is still an internal file
and `agent-link doctor` checks what the adapter reads from it.

## Design

Each section names the options considered and why one was chosen. Facts about Pi were checked
against its 1.0.0 source, not only its documentation; the file is named where it matters.

### What Pi gives

- Extensions are TypeScript modules loaded in the Pi process: `pi -e <file>`, or any file in
  `~/.pi/agent/extensions/` (symbolic links are followed). They see session events and can add
  messages to the conversation.
- A session is one JSONL file, `~/.pi/agent/sessions/--<cwd>--/<time>_<session id>.jsonl`. It is
  created only when the first user or assistant message exists (`session-manager.ts`,
  `_persist`); before that the session lives in memory only.
- Commands run by the model's `bash` tool get `PI_SESSION_ID` and `PI_SESSION_FILE`. Commands
  typed by the human with `!` do not.
- Pi renames its process to `pi` (`ps` shows `pi`, not `node ...`).

### Discovery and registry

Options:

1. Scan `~/.pi/agent/sessions` for recently written files, as the Codex adapter scans rollouts.
   The files say nothing about which are open, in which pane, or how to reach them.
2. Find processes titled `pi` and their panes. That gives a pane, but not the session it shows,
   which changes with `/new` and `/resume` inside the same process.
3. **Chosen:** the extension writes a registry entry, the way Claude Code keeps its own
   `sessions/<pid>.json`. On `session_start` it writes `<dir>/<pid>.json`; it rewrites it on
   every state change and on `/new`, `/resume`, `/fork`, `/reload` (each ends with a new
   `session_start`), and removes it on `session_shutdown`.

`<dir>` is `$XDG_RUNTIME_DIR/agent-link/pi`, or `${XDG_STATE_HOME:-~/.local/state}/agent-link/pi`
when there is no runtime directory; the adapter reads both. The directory is created with
mode 0700, and the adapter ignores one that is not private to the user: a directory others can
write to could hold entries pointing at their sockets. The runtime directory is a tmpfs cleared
at reboot, but within one boot the pid of a killed Pi can be taken by another program.

Entry fields: `protocol` (1), `pid`, `session_id`, `session_file` (empty for `--no-session`),
`cwd`, `name` (Pi's `/name`), `socket`, `state`, `prompt` (title of an open dialog), `mode`
(`tui`, `rpc`, `json`, `print`), `pi_version`.

An entry is live when its pid runs a process titled `pi` (`pi-rpc` in RPC mode); an entry
whose pid now runs something else is stale. The pane is found by process ancestry, as for Claude Code.
`$TMUX_PANE` is not recorded: a pane id like `%3` is unique only inside one tmux server.

Option 2 is still used for one thing: a pane that runs a process titled `pi` but has no live
entry is listed with a note that the extension is not loaded, so a missing extension shows up
in `list` instead of the agent silently missing.

### Delivery

Options for getting text into a running Pi:

1. `tmux send-keys` into the pane: types into the human's editor, mixes with what they are
   typing, gives no acknowledgement. Rejected.
2. RPC mode (`pi --mode rpc`): stdin/stdout protocol for a program that embeds Pi. It replaces
   the terminal UI, so it does not reach a Pi someone works with. Rejected.
3. `pi.sendUserMessage(text)`: stored and shown as a message typed by the human (`role: user`),
   and its text may be expanded as a slash command or prompt template. That blurs the line
   "this is a peer, not your user". Rejected.
4. **Chosen:** `pi.sendMessage({customType: "agent-link", content, display: true},
   {triggerTurn: true, deliverAs: "followUp"})`. Pi stores it as a `custom_message` entry,
   shows it in the pane in its own box, and gives it to the model as user-role text. What the
   model sees is the envelope itself, whose `note:` line says it comes from another agent.

When Pi is idle the message starts a turn. When Pi is busy, `followUp` queues it until the
current work would stop, then Pi runs it in the same run. `steer` (Pi's default for a busy
session) would put it between two tool calls of the human's task: it derails that task, and
the answer to the message would be mixed with the answer to the task. AGENTS.md promises that
a message to a busy agent waits for the current turn; `followUp` keeps that promise.

`sendMessage` with `triggerTurn` skips the check that refuses a typed prompt while a manual
`/compact` runs (`agent-session.ts`, `prompt` versus `sendCustomMessage`). The extension makes
that check itself: when no run is active but Pi is not idle, it refuses the message.

Transport options: a TCP port on localhost (what pi-link uses) is reachable by every local user
and would need its own authentication. **Chosen:** a unix socket `<dir>/<pid>.sock`, mode 0600 in
the 0700 directory: only the same user can connect, the same boundary as Claude Code's inbox.

Wire format: the client writes one line, `{"v": 1, "type": "message", "text": "..."}`, and reads
one line back: `{"ok": true}` or `{"ok": false, "reason": "...", "error": "..."}`.

The extension fails closed. It acts only on a complete line (ended by a newline, at most 1 MiB)
that parses as JSON and carries a non-empty `text`; it then calls `sendMessage` once with the
whole text. A connection closed early, a line too long, bad JSON, a missing session or a running
compaction get an error reply (when the client still listens) and deliver nothing. `ok` means
"handed to Pi": `sendMessage` returns nothing and reports later failures only to Pi's own error
display, so a turn that fails after that shows up as a failed turn, code 6.

### End of a turn

`ask` needs the last thing Pi said in the turn that handled the message, and only once that
turn is over. What Pi writes:

- One assistant message per model response, with `stopReason`: `stop`, `length`, `toolUse`,
  `error`, `aborted`. A response is never split over several records (Claude Code does split
  them); a response that calls a tool carries its text and the call together.
- A turn spans several responses: text and a tool call, the tool result, then the final text.
- A retryable error is written as an assistant message with `stopReason: error`, then Pi waits
  and tries again in the same run (`_prepareRetry` keeps the failed attempt in the file and adds
  a `context_edit` that hides it from the model).
- After a `stop`, Pi can still continue: an extension's `agent_before_settle` may append entries
  and ask for one more response, and queued follow-ups run in the same run.
- `agent_end` fires before retries and continuations; `agent_settled` fires once Pi will not
  continue on its own. `agent_settled` is not written to the file.

So the file alone cannot tell "done" from "about to retry" or "about to continue": the first
`stop` or the first `error` after the message is not final. Options:

1. File only, ending at the first terminal `stopReason`: wrong after a retry (reports a failure
   Pi recovers from) and after a continuation (returns an answer cut short).
2. The registry `state` going back to `idle`: a snapshot from another file. Reading the session
   file and then the state races with a new run, and the registry is gone once Pi exits.
3. **Chosen:** on every `agent_settled` the extension appends a marker to the session with
   `pi.appendEntry("agent-link", {event: "settled"})`. It is a `custom` entry: not part of the
   model's context and not shown in the pane (Pi draws custom entries only for extensions that
   register a renderer). It lands in the same file, in order with the messages, and stays there
   after Pi exits.

The turn that handled message `m-...` is found as follows. Find the `agent-link` custom message
whose text carries the id. From there, the turn ends at the first of:

- a settled marker;
- a new input (a user message, or another `agent-link` message) that follows a finished
  response (`stop` or `length`). That is a queued follow-up taken in the same run: two peers
  asking at once, or the human typing after the answer. Input after a `toolUse` response is
  the human steering the same turn and does not end it.

The answer is the last non-empty assistant text inside that span. The turn failed (code 6) when
the last assistant message in it has `stopReason` `error` or `aborted`; an `error` followed by a
successful retry is not a failure.

### whoami

Options: `PI_SESSION_ID` from the environment, or process ancestry. The variable is set only for
commands the model runs, not for `!` commands, and it is inherited by everything those commands
start, including another agent program started from Pi. Ancestry finds the nearest Pi process,
and the registry maps its pid to the current session (it is rewritten on `/new`).
**Chosen:** ancestry first. When no registered Pi is an ancestor but `PI_SESSION_ID` is set, the
command runs in a Pi without the extension: `whoami` names that session and says it cannot
receive.

### State in `list`

The extension keeps `state` in the registry from Pi's own events: `busy` from `agent_start` to
`agent_settled`, `awaiting-approval` while an extension dialog is open (`ui_prompt_start` to
`ui_prompt_end`; Pi wraps every extension `confirm`, `select`, `input`, `editor` and `custom`
call in these events), otherwise `idle`. The dialog title is kept in `prompt`, so `ask` can say
what is waiting (code 4) without reading the screen. A manual `/compact` is not shown as busy;
a message sent during it is refused with a reason.

### Failure modes

| what happened | what the user sees |
|---|---|
| Pi runs without the extension | `list` shows the pane, kind `pi`, note "agent-link extension not loaded"; `send` exits 3; `whoami` inside it says it cannot receive |
| Pi was killed, its entry stayed | pid not running Pi: not listed; `doctor` counts stale entries |
| Pi exited while `ask` waits | `ask` exits 6, "Pi exited before the turn ended" |
| message queued, then `/new`, `/resume` or `/fork` | Pi drops the queue with the old session; `ask` exits 6, "Pi left this session ... it was dropped" |
| socket missing or refusing | `send` exits 3 naming the socket |
| no acknowledgement in 5 s | `send` exits 3 saying delivery is unknown |
| message during a manual `/compact` | `send` exits 8, "compacting: Pi is compacting its context; try again when it is idle" |
| message over 1 MiB | `send` exits 2 before connecting |
| a dialog blocks the turn | `ask` exits 4 naming the pane and the dialog title |
| the model's turn ends in an error | `ask` exits 6 with Pi's error text |
| `--no-session` (no file) | listed and can receive; `read` and `ask` exit 3: nothing is on disk |
| `pi -p` / `--mode json` | listed while it runs, cannot receive: no socket in a one-shot run |
| registry or file format changed | `doctor` fails the check that names the field or record |
| registry directory open to others, or a socket held by another user | entries ignored, `doctor` fails; `send` exits 3, "nothing sent" |

### Security

The trust boundary stays the user account. The socket and registry live in a 0700 directory of
that user, the socket is 0600, and nothing listens on the network. The adapter does not take
that on faith: it skips a registry directory that is not private to the user, and before
sending it asks the kernel who holds the socket (`SO_PEERCRED`) and refuses a listener of
another uid. The extension writes its entry through a fresh temporary file, never through
whatever already sits at that name. A message is labelled as
coming from a peer and stored as a custom message, not as something the human typed. The
registry holds no secrets; the session file path it names is readable only as the user's own
files are.

### Fit with the adapter interface

`kind = "pi"`, `can_receive`, `can_read` and `reply_detection` true, `subagents` false (Pi has
no subagents of its own). `instances`, `whoami`, `read`, `send`, `poll` follow the interface; the
base `await_reply` is used unchanged, because every state `poll` reports comes from Pi's events
rather than from a screen that could be stale. The conformance test runs it like the other
adapters. Addresses are unchanged: a Pi in tmux session `pi-1` is `pi-1`, outside tmux
`pi#<session id prefix>`.

## Reference

### Session file records the adapter reads

| record | used for |
|---|---|
| `{"type": "message", "message": {"role": "user", "content": ...}}` | `read` (user), input that can end a turn |
| `{"type": "message", "message": {"role": "assistant", "content": [...], "stopReason": ...}}` | `read` (text, tool calls by name, errors), the answer |
| `{"type": "custom_message", "customType": "agent-link", "content": ...}` | `read` (inbox), finding the message by id |
| `{"type": "custom", "customType": "agent-link", "data": {"event": "settled"}}` | end of a run |

Tool results, system messages (Pi's prompt and tool list), model changes and other entries are
skipped. Content is a string or a list of blocks; `text` blocks are read, `toolCall` blocks are
shown by name.

### Loading the extension

For one run: `pi -e /path/to/agent-link/integrations/pi/agent-link.ts`. Permanently:
`install.sh` links it into `~/.pi/agent/extensions/` (or `$PI_CODING_AGENT_DIR/extensions/`).
Loaded twice (both ways at once), the second copy stands down.

## Limits

- A message queued while Pi is busy lives in Pi's memory until it runs; if Pi exits first it is
  lost (`ask` reports that Pi exited).
