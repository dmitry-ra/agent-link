"""Every operation is handle(request dict) -> response dict.

The CLI is a thin printer over this; `agent-link rpc` reads one request as JSON on stdin and
writes the response, which is also how remote nodes will be driven (docs/protocol.md).
"""

import os

from . import address, config, envelope, multiplexers
from .adapters import Context, registry
from .model import NO_INBOX, OK, PROTOCOL, USAGE, CODE_NAMES, AgentRef, LinkError
from .platform import ProcessTable


def context(cfg):
    return Context(cfg["node"], ProcessTable(), multiplexers.all_panes(), cfg["hop_limit"])


def adapters(include_all=False):
    out = registry()
    for a in out:
        if hasattr(a, "include_all"):
            a.include_all = include_all
    return out


def agents(ctx, adapter_list):
    refs = []
    for a in adapter_list:
        refs += a.instances(ctx)
    return address.assign(refs)


def whoami(ctx, adapter_list, refs, pid=None, env=None):
    pid = pid or os.getpid()
    env = env if env is not None else dict(os.environ)
    # Agents nest (Pi started from Claude Code, Claude Code from Codex) and environment variables
    # are inherited, so several adapters may claim this process: the nearest agent process wins.
    # Ties (no known process) go to Codex, whose thread id is explicit.
    anc = ctx.table.ancestors(pid)
    found = [me for me in (a.whoami(ctx, pid, env) for a in sorted(adapter_list, key=lambda a: a.kind != "codex")) if me]
    if found:
        me = min(found, key=lambda r: anc.index(str(r.private.get("pid"))) if str(r.private.get("pid")) in anc
                 else len(anc))
        for r in refs:
            if r.kind == me.kind and r.instance == me.instance:
                return r
        address.assign([me])
        return me
    pane = multiplexers.pane_of(pid, ctx.panes, ctx.table)
    me = AgentRef(kind="human", node=ctx.node, instance=str(pid), session=pane.session if pane else "",
                  position=pane.position if pane else "", can_receive=False,
                  note="not inside a known agent; messages from here cannot be answered")
    me.address = f"{pane.session}:{pane.position}" if pane else f"human#{pid}"
    return me


def doctor_checks(raw):
    """(checks, ok) from (kind, ok, text) triples, where ok None means the program is absent here.

    A program that is not installed is not a fault of agent-link; only a present program whose
    formats or prerequisites do not match is a failure.
    """
    checks = [{"ok": ok is not False, "state": "absent" if ok is None else "ok" if ok else "fail",
               "text": f"{kind}: {text}" if kind else text} for kind, ok, text in raw]
    return checks, not any(c["state"] == "fail" for c in checks)


def adapter_for(ref, adapter_list):
    for a in adapter_list:
        if a.kind == ref.kind:
            return a
    raise LinkError(NO_INBOX, f"no adapter for kind {ref.kind!r}")


def handle(req):
    try:
        return _handle(req)
    except LinkError as e:
        return {"protocol": PROTOCOL, "ok": False, "code": e.code, "status": CODE_NAMES.get(e.code, str(e.code)), "error": str(e)}


def _handle(req):
    op = req.get("op")
    cfg = config.load()
    ctx = context(cfg)
    alist = adapters(include_all=bool(req.get("all")))
    refs = agents(ctx, alist)
    me = whoami(ctx, alist, refs)
    base = {"protocol": PROTOCOL, "node": ctx.node}

    if op == "whoami":
        return {**base, "ok": True, "code": OK, "me": me.public(), "address": f"{me.address}@{ctx.node}"}

    if op == "list":
        return {**base, "ok": True, "code": OK, "me": me.address, "panes": len(ctx.panes),
                "kinds": [a.kind for a in alist], "agents": [r.public() for r in sorted(refs, key=lambda r: r.address)]}

    if op == "doctor":
        present = os.path.exists(cfg["path"])
        raw = [("", True, f"config {cfg['path']} ({'loaded' if present else 'absent, defaults'}; node {ctx.node})"),
               ("", True if ctx.panes else None,
                f"{len(ctx.panes)} multiplexer panes" if ctx.panes else "no tmux panes yet: agents are found only inside tmux")]
        for a in alist:
            raw += [(a.kind, ok, text) for ok, text in a.doctor(ctx)]
        checks, ok = doctor_checks(raw)
        return {**base, "ok": ok, "code": OK if ok else NO_INBOX, "checks": checks}

    if op not in ("read", "send", "ask", "status"):
        raise LinkError(USAGE, f"unknown op {op!r}")
    target = address.resolve(req.get("to", ""), refs, ctx.node, cfg["aliases"])
    a = adapter_for(target, alist)

    if op == "read":
        return {**base, "ok": True, "code": OK, "agent": target.public(),
                "entries": a.read(ctx, target, int(req.get("limit", 30)))}

    if op == "status":
        code, status, text = a.poll(ctx, target, req.get("message", ""))
        return {**base, "ok": True, "code": OK, "agent": target.public(), "message": req.get("message", ""),
                "message_status": status, "detail": text}

    if target.kind == me.kind and target.instance == me.instance:
        raise LinkError(USAGE, f"{target.address} is you")
    text = req.get("text", "")
    if not text.strip():
        raise LinkError(USAGE, "empty message")
    env_ = envelope.make(f"{me.address}@{ctx.node}", me.kind, f"{target.address}@{ctx.node}", text,
                         conversation=req.get("conversation"), hops=req.get("hops", 0),
                         hop_limit=ctx.hop_limit, can_reply=me.can_receive, waiting=(op == "ask"))
    receipt = a.send(ctx, target, envelope.render(env_))
    receipt.to, receipt.message_id = target.address, env_.message_id
    out = {**base, "ok": receipt.code == OK, "code": receipt.code, "status": CODE_NAMES.get(receipt.code),
           "receipt": receipt.public(), "conversation": env_.conversation, "hops": env_.hops}
    if op == "send" or receipt.code != OK:
        return out
    code, answer = a.await_reply(ctx, target, env_.message_id, int(req.get("timeout", 600)))
    return {**out, "ok": code == OK, "code": code, "status": CODE_NAMES.get(code), "answer": answer}
