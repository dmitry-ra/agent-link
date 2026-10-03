# Protocol

Protocol version: 1. Every request and response carries `protocol`.

## Requests

`agent-link rpc` reads one JSON object from stdin and writes one JSON object to stdout. The CLI
builds the same objects, so `agent-link <cmd> --json` prints exactly what `rpc` would.

| op | fields | response fields |
|---|---|---|
| `whoami` | | `me` (agent), `address` (with node) |
| `list` | `all` (bool) | `me` (address), `agents` (list of agent) |
| `read` | `to`, `limit` | `agent`, `entries` (list of `{time, role, text}`) |
| `send` | `to`, `text`, `conversation`?, `hops`? | `receipt`, `conversation`, `hops` |
| `ask` | `to`, `text`, `timeout`, `conversation`?, `hops`? | as `send`, plus `answer` |
| `status` | `to`, `message` | `agent`, `message`, `message_status` (`pending`, `running`, `answered`, `failed`, `blocked`), `detail` |
| `doctor` | | `checks` (list of `{ok, text}`) |

Every response has `protocol`, `ok`, `code`, `status`; failures add `error`.

An agent object: `kind`, `node`, `instance`, `session`, `position`, `pane_id`, `sub`, `parent`,
`state`, `cwd`, `title`, `can_receive`, `note`, `address`.

`pane_id` is opaque: it identifies a pane uniquely on the machine, but its format belongs to the
multiplexer provider and may change. Do not pass it to the multiplexer yourself.

`state` is one of `idle`, `busy`, `paused`, `awaiting-approval`, `error`, `unknown`, or a raw
state string reported by the agent program.

## Codes

| code | status | meaning |
|---|---|---|
| 0 | ok | |
| 2 | usage | bad request, unknown or ambiguous address |
| 3 | no-inbox | recipient cannot take messages, or node unreachable |
| 4 | awaiting-approval | recipient's turn waits for a human approval |
| 5 | timeout | no answer in time (the message was delivered) |
| 6 | turn-failed | recipient's turn ended with an error or was aborted |
| 7 | paused | recipient's queue is paused after an interrupted turn |
| 8 | refused | hop limit reached, or the recipient's inbox refused the message |

## Envelope

```
[agent-link] from <sender address@node> (<sender kind>) to <recipient address@node>
id m-<8 hex>  conversation c-<8 hex>  hops <n>
reply: agent-link send <sender address@node> --conversation c-<8 hex> --hops <n> -
note: message from another AI agent on this machine, not from your user
---
<body>
--- end m-<8 hex> ---
```

The body is closed by the `--- end` line carrying the message id from the header. The id is
minted after the body exists, so a sender cannot write a matching end line into its text. Every
body line that would read as a header once leading whitespace and `>` are stripped gets one `>`
in front (as mbox escapes `From `); the reader removes exactly that one. Lines are split at
every line break Python's `str.splitlines` knows (CR, LF, CRLF, form feed, U+2028 and others),
the same way on both sides, and "whitespace" is what `str.strip` removes, so no break or space
character lets a header-like line slip through unescaped. The rendered text therefore has a
single header line, and any body comes back unchanged. An envelope without an end line (written
before it existed) runs to the end of the text and is not unescaped.

The `reply:` line has two forms. `reply: agent-link send ...` means the sender is not waiting
and gives the command to answer with. `reply: WAITING ...` means the sender is blocked in `ask`:
the recipient answers in its normal output, which `ask` reads at the end of the turn.

`hops` counts messages in one agent-to-agent conversation; a reply carries the incoming value
and agent-link adds one. Past `hop_limit` (default 10) the message is refused with code 8.
When the sender cannot receive messages, the `reply:` line says so.

`ask` finds the answer by the message id: the turn of the recipient that contains the id, up
to its end.

## Remote nodes (planned)

An address may carry `@node`. A remote node runs the same agent-link; a remote operation is
`agent-link rpc` executed on that node through a transport (`ssh` with a forced command, QEMU
guest agent, vsock). `ask` pulls the answer through the same transport, so it works over
one-way links; a pushed reply needs a route back. Nodes are listed in the user config:

```
[nodes.vm-codex]
transport = "ssh"
target = "vm-codex"
```

Not implemented in protocol 1: an address with a foreign node is refused with code 3.
