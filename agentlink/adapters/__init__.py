"""Adapters: one module per kind of agent. The core knows nothing about any of them.

To add a kind of agent, copy _template.py, implement the methods, register the class in
ADAPTERS below, add fixtures and tests (tests/conformance.py must pass), and describe the
harness in docs/adapters/<kind>.md. See docs/adding-an-adapter.md.
"""

from ..model import NO_INBOX, LinkError


class Context:
    """Live machine state, gathered once per command and shared by all adapters."""

    def __init__(self, node, table, panes, hop_limit=10):
        self.node = node
        self.table = table
        self.panes = panes
        self.hop_limit = hop_limit
        self.pane_by_id = {p.pane_id: p for p in panes}


class Adapter:
    kind = "base"
    # What the harness supports; conformance tests hold adapters to these claims.
    can_receive = False          # send() can deliver to it
    can_read = False             # read() returns its conversation
    reply_detection = False      # await_reply() can find the answer to a message
    subagents = False            # instances() may return subagents

    def instances(self, ctx):
        """Every live agent of this kind on this machine, as AgentRef (address left empty)."""
        return []

    def whoami(self, ctx, pid, env):
        """The AgentRef of the agent this process runs inside, or None."""
        return None

    def read(self, ctx, ref, limit):
        """Recent conversation entries: list of {"time", "role", "text"}, oldest first."""
        raise LinkError(NO_INBOX, f"{self.kind}: reading is not supported")

    def send(self, ctx, ref, text):
        """Deliver text; return a Receipt."""
        raise LinkError(NO_INBOX, f"{self.kind}: sending is not supported")

    def await_reply(self, ctx, ref, message_id, timeout):
        """Wait for the answer to the message carrying message_id; return (code, text)."""
        raise LinkError(NO_INBOX, f"{self.kind}: waiting for replies is not supported")

    def doctor(self, ctx):
        """Checks of the formats and prerequisites this adapter relies on: list of (ok, text)."""
        return []


def registry():
    from .claude_code import ClaudeCode
    from .codex_cli import CodexCli
    return [ClaudeCode(), CodexCli()]
