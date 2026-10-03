"""Adapters: one module per kind of agent. The core knows nothing about any of them.

To add a kind of agent, copy _template.py, implement the methods, register the class in
ADAPTERS below, add fixtures and tests (tests/conformance.py must pass), and describe the
harness in docs/adapters/<kind>.md. See docs/adding-an-adapter.md.
"""

import time

from ..model import NO_INBOX, TIMEOUT, LinkError


def timeout_text(message_id, timeout, status):
    """What a caller learns from a timeout. "pending" means the message was never seen in the
    recipient's transcript: queued behind a turn, or never arrived; resending would duplicate it."""
    if status == "pending":
        return (f"no answer to {message_id} within {timeout}s: not observed in the recipient's transcript "
                "(still queued, or never arrived); check with agent-link status before sending again")
    return f"no answer to {message_id} within {timeout}s (status {status})"


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
        """The AgentRef of the agent this process runs inside, or None.

        Put the agent's own process id in private["pid"] when it is known: when several adapters
        claim the process, the one whose agent process is the nearest ancestor wins.
        """
        return None

    def read(self, ctx, ref, limit):
        """Recent conversation entries: list of {"time", "role", "text"}, oldest first."""
        raise LinkError(NO_INBOX, f"{self.kind}: reading is not supported")

    def send(self, ctx, ref, text):
        """Deliver text; return a Receipt."""
        raise LinkError(NO_INBOX, f"{self.kind}: sending is not supported")

    def poll(self, ctx, ref, message_id):
        """One look at the message carrying message_id: (code, status, text).

        status: pending (not picked up yet), running, answered, failed, blocked.
        code: OK when answered, otherwise the code a waiting caller would get now.
        """
        raise LinkError(NO_INBOX, f"{self.kind}: following a message is not supported")

    def await_reply(self, ctx, ref, message_id, timeout):
        """Poll until the message is answered or fails; return (code, text)."""
        deadline = time.time() + timeout
        while True:
            code, status, text = self.poll(ctx, ref, message_id)
            if status in ("answered", "failed", "blocked"):
                return code, text
            if time.time() >= deadline:
                return TIMEOUT, timeout_text(message_id, timeout, status)
            time.sleep(2)

    def doctor(self, ctx):
        """Checks of the formats and prerequisites this adapter relies on: list of (ok, text)."""
        return []


def registry():
    from .claude_code import ClaudeCode
    from .codex_cli import CodexCli
    from .pi import Pi
    return [ClaudeCode(), CodexCli(), Pi()]
