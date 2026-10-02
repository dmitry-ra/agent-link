"""Address grammar, assignment and resolution.

    address  := target ["@" node]
    target   := session [":" window "." pane] ["/" sub]
              | kind "#" id-prefix ["/" sub]

    project-1            the agent in multiplexer session project-1
    project-1:2.1        a specific pane, needed only when the session holds several agents
    codex-1/reviewer     subagent "reviewer" of the agent in codex-1
    codex#9f3a1c2e       an agent outside any multiplexer, by kind and id prefix
    project-1@box        on node box (omitted node = this machine)

Addresses are computed from live state on every call; nothing is cached on disk.
"""

import re
from dataclasses import dataclass

from .model import NO_INBOX, USAGE, LinkError

NAME = r"[A-Za-z0-9][A-Za-z0-9_.+-]*"
GRAMMAR = re.compile(
    rf"^(?:(?P<kind>[a-z][a-z0-9-]*)#(?P<ident>[0-9A-Za-z-]+)|(?P<session>{NAME})(?::(?P<pos>\d+\.\d+))?)"
    rf"(?:/(?P<sub>[A-Za-z0-9_./-]+?))?(?:@(?P<node>{NAME}))?$"
)
MIN_ID = 4


@dataclass
class Address:
    session: str = ""
    position: str = ""
    kind: str = ""
    ident: str = ""
    sub: str = ""
    node: str = ""


def parse(text):
    m = GRAMMAR.match(text.strip())
    if not m:
        raise LinkError(USAGE, f"not an agent address: {text!r} (see AGENTS.md, Addresses)")
    a = Address(**{k: v or "" for k, v in m.groupdict().items() if k != "pos"}, position=m.group("pos") or "")
    if a.kind and len(a.ident) < MIN_ID:
        raise LinkError(USAGE, f"id prefix in {text!r} is too short: use at least {MIN_ID} characters")
    return a


def assign(refs):
    """Give every AgentRef its shortest unambiguous address on this node."""
    top = [r for r in refs if not r.sub]
    per_session = {}
    for r in top:
        if r.session:
            per_session.setdefault(r.session, []).append(r)
    for r in top:
        if r.session:
            shared = len(per_session[r.session]) > 1
            r.address = f"{r.session}:{r.position}" if shared else r.session
        else:
            r.address = f"{r.kind}#{r.instance[:8]}"
    # Equal session names in two tmux servers (each server's first session is "0") would give
    # two agents one address; such agents are named by kind and id instead.
    groups = {}
    for r in top:
        groups.setdefault(r.address, []).append(r)
    for same in groups.values():
        if len(same) > 1:
            for r in same:
                r.address = f"{r.kind}#{r.instance[:8]}"
    by_instance = {r.instance: r for r in top}
    for r in refs:
        if r.sub:
            parent = by_instance.get(r.parent)
            base = parent.address if parent else f"{r.kind}#{r.parent[:8]}"
            r.address = f"{base}/{r.sub}"
    return refs


def full(ref, node):
    return f"{ref.address}@{node}"


def resolve(text, refs, node, aliases=None):
    """The one AgentRef the text names. Unknown or ambiguous addresses are errors, never guesses."""
    text = text.strip()
    if aliases and text.split("@")[0] in aliases:
        head, _, at = text.partition("@")
        text = aliases[head] + (f"@{at}" if at else "")
    a = parse(text)
    if a.node and a.node != node:
        raise LinkError(NO_INBOX, f"node {a.node!r} is not this machine ({node!r}); remote nodes are not supported yet")
    if a.kind:
        cands = [r for r in refs if r.kind == a.kind and r.sub == a.sub and r.instance.startswith(a.ident)]
    else:
        cands = [r for r in refs if r.session == a.session and r.sub == a.sub
                 and (not a.position or r.position == a.position)]
    if not cands and not a.kind and not a.position and not a.sub:
        # The agent program's own session name (e.g. Claude Code's "project-3a") also works.
        cands = [r for r in refs if r.title == a.session and not r.sub]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        known = ", ".join(sorted(r.address for r in refs)) or "none"
        raise LinkError(USAGE, f"no agent at {text!r}; known addresses: {known}")
    raise LinkError(USAGE, f"{text!r} is ambiguous: " + ", ".join(sorted(r.address for r in cands)))
