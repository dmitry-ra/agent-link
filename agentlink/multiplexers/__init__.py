"""Terminal multiplexer providers: where agents live and what their screens show.

A provider returns Pane records. The session name of a pane is the stable part of an agent
address: it survives agent restarts. Add a provider (zellij, screen) as a module with the
same three functions as tmux.py and list it in PROVIDERS.
"""

from dataclasses import dataclass

from . import tmux


@dataclass
class Pane:
    provider: str
    session: str      # stable name, the address of the agent inside
    position: str     # "window.pane", e.g. "1.1"
    pane_id: str      # provider id, e.g. tmux "%0"
    pid: str          # pid of the process the pane started
    cwd: str


PROVIDERS = [tmux]


def all_panes():
    panes = []
    for p in PROVIDERS:
        panes += p.panes(Pane)
    return panes


def screen(pane):
    for p in PROVIDERS:
        if p.NAME == pane.provider:
            return p.screen(pane)
    return ""


def pane_of(pid, panes, table):
    """The pane whose process tree contains pid, or None."""
    by_pid = {p.pid: p for p in panes}
    for anc in table.ancestors(pid):
        if anc in by_pid:
            return by_pid[anc]
    return None
