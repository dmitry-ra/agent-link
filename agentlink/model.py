"""Data types and result codes shared by the core and every adapter."""

from dataclasses import asdict, dataclass, field

PROTOCOL = 1

OK = 0
USAGE = 2               # bad call, unknown or ambiguous address
NO_INBOX = 3            # recipient does not take messages (no inbox, gone, node unreachable)
AWAITING_APPROVAL = 4   # recipient's turn waits for a human approval dialog
TIMEOUT = 5
TURN_FAILED = 6         # recipient's turn ended with an error or was aborted
PAUSED = 7              # recipient's queue is paused after an interrupted turn
REFUSED = 8             # refused by the recipient or by the hop limit

CODE_NAMES = {OK: "ok", USAGE: "usage", NO_INBOX: "no-inbox", AWAITING_APPROVAL: "awaiting-approval",
              TIMEOUT: "timeout", TURN_FAILED: "turn-failed", PAUSED: "paused", REFUSED: "refused"}


class LinkError(Exception):
    def __init__(self, code, message, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


@dataclass
class AgentRef:
    kind: str                       # adapter kind: "claude", "codex", ...
    node: str                       # machine name
    instance: str                   # changes on restart: pid, thread id
    session: str = ""               # multiplexer session name; empty outside a multiplexer
    position: str = ""              # "window.pane" inside the session
    pane_id: str = ""               # multiplexer pane id
    sub: str = ""                   # subagent path inside its parent, e.g. "reviewer"
    parent: str = ""                # parent instance for subagents
    state: str = "unknown"          # idle | busy | paused | awaiting-approval | error | unknown
    cwd: str = ""
    title: str = ""
    can_receive: bool = True
    note: str = ""                  # why it cannot receive, or other caveat
    address: str = ""               # assigned by address.assign()
    private: dict = field(default_factory=dict)   # adapter-only data, never printed

    def public(self):
        d = asdict(self)
        d.pop("private")
        return d


@dataclass
class Receipt:
    code: int
    text: str
    to: str = ""
    instance: str = ""
    message_id: str = ""

    def public(self):
        d = asdict(self)
        d["status"] = CODE_NAMES.get(self.code, str(self.code))
        return d
