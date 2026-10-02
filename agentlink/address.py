"""Address grammar, assignment and resolution.

    address  := target ["@" node]
    target   := session [":" window "." pane] ["/" sub]
              | kind "#" id-prefix ["/" sub]

    project-1            the agent in multiplexer session project-1
    project-1:2.1        a specific pane, needed only when the session holds several agents
    codex-1/reviewer     subagent "reviewer" of the agent in codex-1
    codex#9f3a1c2e       by kind and id prefix: an agent outside any multiplexer, or one whose
                         session address another agent shares (equal session names in two
                         tmux servers)
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
    """Give every AgentRef the shortest address on this node that no other agent shares.

    An agent climbs session, session:pane, kind#id prefix, kind#full id until its address is
    unique: two tmux servers can hold equal session names, and Codex thread ids (UUIDv7) share
    their first characters when started within a minute of each other.
    """
    top = [r for r in refs if not r.sub]

    def ladder(r):
        steps = [r.session, f"{r.session}:{r.position}"] if r.session else []
        return steps + [f"{r.kind}#{r.instance[:8]}", f"{r.kind}#{r.instance}"]

    level = {id(r): 0 for r in top}
    while True:
        groups = {}
        for r in top:
            steps = ladder(r)
            r.address = steps[min(level[id(r)], len(steps) - 1)]
            groups.setdefault(r.address, []).append(r)
        clash = [r for g in groups.values() if len(g) > 1 for r in g if level[id(r)] < len(ladder(r)) - 1]
        if not clash:
            break
        for r in clash:
            level[id(r)] += 1
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
    # Every address assign() handed out is unique, so it names its agent even where the
    # grammar below would match a second one (an id prefix shared with a session agent).
    exact = [r for r in refs if r.address and r.address == text.split("@")[0]]
    if len(exact) == 1:
        return exact[0]
    if a.kind:
        # In kind#id/sub the id is the parent's.
        cands = [r for r in refs if r.kind == a.kind and r.sub == a.sub
                 and (r.parent if a.sub else r.instance).startswith(a.ident)]
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
