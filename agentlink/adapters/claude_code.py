"""Claude Code adapter.

Relies on files Claude Code maintains itself (undocumented, checked by doctor()):
  <config>/sessions/<pid>.json     one per live session: sessionId, cwd, tmux, messagingSocketPath,
                                   status, kind, version. <pid>.*.key files are secrets: never read.
  <config>/projects/*/<sessionId>.jsonl   the conversation.
<config> is $CLAUDE_CONFIG_DIR or ~/.claude. Messages go to the session's inbox socket.
"""

import json
import os
import time
from pathlib import Path

from ..model import NO_INBOX, OK, REFUSED, TIMEOUT, USAGE, AgentRef, LinkError, Receipt
from . import Adapter
from ._claude_inbox import deliver

STATUS = {"busy": "busy", "idle": "idle", "waiting": "awaiting-approval"}
REQUIRED = ("pid", "sessionId", "cwd")


def config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def registry_entries(base=None):
    out = []
    for f in sorted((base or config_dir() / "sessions").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if all(k in d for k in REQUIRED):
            out.append(d)
    return out


def split_tmux(field):
    """'homelab-1:@0.%0' -> ('homelab-1', '%0'). The session name may itself contain ':'."""
    if not field or "%" not in field:
        return "", ""
    session, _, rest = field.rpartition(":")
    return session, rest[rest.index("%"):]


def transcript_path(session_id, base=None):
    for f in (base or config_dir() / "projects").glob(f"*/{session_id}.jsonl"):
        return f
    return None


def entry_text(d):
    """(role, text) a reader cares about, or None."""
    t = d.get("type")
    if t == "queue-operation" and d.get("operation") == "enqueue":
        return "inbox", str(d.get("content", ""))
    if t not in ("user", "assistant"):
        return None
    m = d.get("message") or {}
    c = m.get("content")
    if isinstance(c, str):
        return m.get("role", t), c
    if not isinstance(c, list):
        return None
    texts = [x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text"]
    calls = [x.get("name", "") for x in c if isinstance(x, dict) and x.get("type") == "tool_use"]
    if texts:
        return m.get("role", t), "\n".join(texts)
    if calls:
        return "call", ", ".join(calls)
    return None


def answer_after(lines, tag):
    """(status, answer) for the turn that handled the message carrying tag.

    status: pending (message not seen), running, done. The answer is the text of the last
    assistant entry up to the first end_turn after the message.
    """
    seen, last = False, ""
    for line in lines:
        if not seen:
            seen = tag in line
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "assistant":
            continue
        m = d.get("message") or {}
        texts = [x.get("text", "") for x in m.get("content") or [] if isinstance(x, dict) and x.get("type") == "text"]
        if texts:
            last = "\n".join(texts)
        if m.get("stop_reason") == "end_turn":
            return "done", last
    return ("running" if seen else "pending"), last


class ClaudeCode(Adapter):
    kind = "claude"
    can_receive = True
    can_read = True
    reply_detection = True
    subagents = False

    def __init__(self, sessions_dir=None, projects_dir=None):
        self.sessions_dir = sessions_dir
        self.projects_dir = projects_dir

    def _ref(self, ctx, d):
        session, pane_id = split_tmux(d.get("tmux", ""))
        pane = ctx.pane_by_id.get(pane_id)
        sock = d.get("messagingSocketPath", "")
        return AgentRef(
            kind=self.kind, node=ctx.node, instance=d["sessionId"],
            session=pane.session if pane else session, position=pane.position if pane else "",
            pane_id=pane_id, state=STATUS.get(d.get("status", ""), d.get("status") or "unknown"),
            cwd=d.get("cwd", ""), title=d.get("name", ""),
            can_receive=bool(sock) and d.get("kind") == "interactive",
            note="" if sock else "no inbox socket (not an interactive session)",
            private={"pid": str(d["pid"]), "socket": sock, "version": d.get("version", "")},
        )

    def instances(self, ctx):
        base = self.sessions_dir or config_dir() / "sessions"
        return [self._ref(ctx, d) for d in registry_entries(base) if ctx.table.alive(d["pid"])]

    def whoami(self, ctx, pid, env):
        by_pid = {str(d["pid"]): d for d in registry_entries(self.sessions_dir or config_dir() / "sessions")}
        for anc in ctx.table.ancestors(pid):
            if anc in by_pid:
                return self._ref(ctx, by_pid[anc])
        return None

    def _lines(self, ref):
        path = transcript_path(ref.instance, self.projects_dir)
        if not path:
            raise LinkError(NO_INBOX, f"no transcript for {ref.address} (session {ref.instance})")
        return path.read_text(encoding="utf-8", errors="replace").splitlines()

    def read(self, ctx, ref, limit):
        out = []
        for line in self._lines(ref):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            got = entry_text(d)
            if got:
                out.append({"time": (d.get("timestamp") or "")[11:19], "role": got[0], "text": got[1]})
        return out[-limit:]

    def send(self, ctx, ref, text):
        if not ref.can_receive:
            raise LinkError(NO_INBOX, f"{ref.address}: {ref.note or 'cannot receive'}")
        status, detail = deliver(ref.private["socket"], text, name=None)
        code = {"delivered": OK, "no-inbox": NO_INBOX, "too-large": USAGE}.get(status, REFUSED)
        return Receipt(code, detail or status, instance=ref.instance)

    def await_reply(self, ctx, ref, message_id, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, answer = answer_after(self._lines(ref), message_id)
            if status == "done":
                return OK, answer
            time.sleep(2)
        return TIMEOUT, f"no end of turn after {message_id} within {timeout}s"

    def doctor(self, ctx):
        base = self.sessions_dir or config_dir() / "sessions"
        checks = [(base.is_dir(), f"session registry {base}")]
        entries = registry_entries(base)
        live = [d for d in entries if ctx.table.alive(d["pid"])]
        checks.append((True, f"{len(live)} live of {len(entries)} registered sessions"))
        for d in live:
            missing = [k for k in ("tmux", "messagingSocketPath", "status", "kind") if k not in d]
            checks.append((not missing, f"session {d['pid']} (v{d.get('version', '?')}): "
                                        + ("fields ok" if not missing else f"missing {missing}")))
            checks.append((transcript_path(d["sessionId"], self.projects_dir) is not None,
                           f"session {d['pid']}: transcript found"))
        return checks
