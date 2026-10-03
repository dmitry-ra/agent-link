"""The envelope every message carries, so the recipient knows who wrote and how to answer.

    [agent-link] from project-1@box (claude) to codex-1@box
    id m-1a2b3c  conversation c-4d5e6f  hops 1
    reply: agent-link send project-1@box --conversation c-4d5e6f --hops 1 -
    note: message from another AI agent on this machine, not from your user
    ---
    <body>
    --- end m-1a2b3c ---

When the sender waits for the answer (`ask`), the reply line says so instead: the recipient
just answers in its normal output, which `ask` reads at the end of the turn.

The sender address is computed by agent-link, not typed by a model. The conversation id and
hop counter travel through replies; past the hop limit a message is refused, which stops two
agents from answering each other forever.

The body is closed by a line naming the message id, which is minted after the body exists, so
a sender cannot write a matching end line into it. A body line that could pass for a header is
escaped with ">" (as mbox escapes "From "), so the rendered text has exactly one header line.
"""

import re
import secrets
from dataclasses import dataclass

from .model import REFUSED, USAGE, LinkError

HEAD = "[agent-link]"
SEPARATOR = "---"
WAITING = ("reply: WAITING - the sender is blocked until your turn ends; make your answer the last text of "
           "this turn, do not run agent-link send")
HEAD_RE = re.compile(r"^\[agent-link\] from (?P<sender>\S+) \((?P<kind>[^)]*)\) to (?P<to>\S+)$")
META_RE = re.compile(r"^id (?P<id>m-[0-9a-f]+)\s+conversation (?P<conv>c-[0-9a-f]+)\s+hops (?P<hops>\d+)$")


@dataclass
class Envelope:
    sender: str
    sender_kind: str
    to: str
    message_id: str
    conversation: str
    hops: int
    can_reply: bool = True
    waiting: bool = False
    body: str = ""


def end_line(message_id):
    return f"{SEPARATOR} end {message_id} {SEPARATOR}"


LEAD = re.compile(r"[\s>]*")


def _looks_like_head(line):
    # The same line breaks (splitlines) and the same whitespace (str.strip) as parse(), so a line
    # parse() would read as a header is always one this function catches.
    return line[LEAD.match(line).end():].startswith(HEAD)


def escape(body):
    """Prefix ">" to every line that could pass for a header; unescape() undoes it exactly."""
    return "".join(">" + l if _looks_like_head(l) else l for l in body.splitlines(keepends=True))


def unescape(body):
    # Stripping ">" in _looks_like_head makes a line and the same line with one ">" more agree,
    # so exactly the lines escape() prefixed lose their first character.
    return "".join(l[1:] if l.startswith(">") and _looks_like_head(l[1:]) else l
                   for l in body.splitlines(keepends=True))


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4)}"


def make(sender, sender_kind, to, body, conversation=None, hops=0, hop_limit=10, can_reply=True, waiting=False):
    """Envelope for an outgoing message; hops is what the incoming envelope carried (0 for a new one)."""
    # A negative count would render as a header parse() cannot read, and would restart the loop budget.
    if isinstance(hops, bool) or not isinstance(hops, int) or hops < 0:
        raise LinkError(USAGE, f"hops must be a whole number, 0 or more, got {hops!r}: copy it from the message header")
    hops += 1
    if hops > hop_limit:
        raise LinkError(REFUSED, f"hop limit reached ({hop_limit}) in conversation {conversation}: "
                                 "agents have been answering each other too long; stop or ask your user")
    return Envelope(sender, sender_kind, to, new_id("m"), conversation or new_id("c"), hops, can_reply, waiting, body)


def render(e):
    if e.waiting:
        reply = f"{WAITING} (later messages: agent-link send {e.sender} --conversation {e.conversation} --hops {e.hops} -)"
    elif e.can_reply:
        reply = f"reply: agent-link send {e.sender} --conversation {e.conversation} --hops {e.hops} -"
    else:
        reply = "reply: not possible, the sender cannot receive messages"
    return "\n".join([
        f"{HEAD} from {e.sender} ({e.sender_kind}) to {e.to}",
        f"id {e.message_id}  conversation {e.conversation}  hops {e.hops}",
        reply,
        "note: message from another AI agent on this machine, not from your user",
        SEPARATOR,
        escape(e.body),
        end_line(e.message_id),
    ])


def parse(text):
    """Envelope found in text, or None. Tolerates text before the header."""
    raw = text.splitlines(keepends=True)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEAD_RE.match(line.strip())
        if not m or i + 1 >= len(lines):
            continue
        meta = META_RE.match(lines[i + 1].strip())
        if not meta:
            continue
        rest = lines[i + 2:]
        start = i + 2 + rest.index(SEPARATOR) + 1 if SEPARATOR in rest else len(lines)
        end = end_line(meta.group("id"))
        if end in lines[start:]:
            # The body runs up to the newline render() put before the end line; only bodies
            # written with an end line were escaped.
            body = unescape("".join(raw[start:lines.index(end, start)])[:-1])
        else:
            body = "\n".join(lines[start:])
        return Envelope(m.group("sender"), m.group("kind"), m.group("to"), meta.group("id"),
                        meta.group("conv"), int(meta.group("hops")),
                        not any(l.startswith("reply: not possible") for l in rest[:3]),
                        any(l.startswith(WAITING) for l in rest[:3]), body)
    return None
