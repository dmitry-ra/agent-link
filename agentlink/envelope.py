"""The envelope every message carries, so the recipient knows who wrote and how to answer.

    [agent-link] from homelab-1@hel (claude) to codex-1@hel
    id m-1a2b3c  conversation c-4d5e6f  hops 1
    reply: agent-link send homelab-1@hel --conversation c-4d5e6f --hops 1 -
    note: message from another AI agent on this machine, not from your user
    ---
    <body>

The sender address is computed by agent-link, not typed by a model. The conversation id and
hop counter travel through replies; past the hop limit a message is refused, which stops two
agents from answering each other forever.
"""

import re
import secrets
from dataclasses import dataclass

from .model import REFUSED, LinkError

HEAD = "[agent-link]"
SEPARATOR = "---"
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
    body: str = ""


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4)}"


def make(sender, sender_kind, to, body, conversation=None, hops=0, hop_limit=10, can_reply=True):
    """Envelope for an outgoing message; hops is what the incoming envelope carried (0 for a new one)."""
    hops = int(hops) + 1
    if hops > hop_limit:
        raise LinkError(REFUSED, f"hop limit reached ({hop_limit}) in conversation {conversation}: "
                                 "agents have been answering each other too long; stop or ask your user")
    return Envelope(sender, sender_kind, to, new_id("m"), conversation or new_id("c"), hops, can_reply, body)


def render(e):
    reply = (f"reply: agent-link send {e.sender} --conversation {e.conversation} --hops {e.hops} -"
             if e.can_reply else "reply: not possible, the sender cannot receive messages")
    return "\n".join([
        f"{HEAD} from {e.sender} ({e.sender_kind}) to {e.to}",
        f"id {e.message_id}  conversation {e.conversation}  hops {e.hops}",
        reply,
        "note: message from another AI agent on this machine, not from your user",
        SEPARATOR,
        e.body,
    ])


def parse(text):
    """Envelope found in text, or None. Tolerates text before the header."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEAD_RE.match(line.strip())
        if not m or i + 1 >= len(lines):
            continue
        meta = META_RE.match(lines[i + 1].strip())
        if not meta:
            continue
        rest = lines[i + 2:]
        body = rest[rest.index(SEPARATOR) + 1:] if SEPARATOR in rest else []
        return Envelope(m.group("sender"), m.group("kind"), m.group("to"), meta.group("id"),
                        meta.group("conv"), int(meta.group("hops")),
                        not any(l.startswith("reply: not possible") for l in rest[:3]), "\n".join(body))
    return None
