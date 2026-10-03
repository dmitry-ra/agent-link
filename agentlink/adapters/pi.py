"""Pi adapter.

Pi keeps no registry of running sessions and has no inbox; the agent-link extension
(integrations/pi/agent-link.ts) adds both. Facts relied on (Pi 1.0.0; checked by doctor()):
  <dir>/<pid>.json   one per live Pi that loaded the extension: protocol, pid, session_id,
                     session_file, cwd, name, socket, state, prompt, mode, pi_version.
                     <dir> is $XDG_RUNTIME_DIR/agent-link/pi, else
                     ${XDG_STATE_HOME:-~/.local/state}/agent-link/pi.
  <dir>/<pid>.sock   takes one line {"v": 1, "type": "message", "text": ...} and answers one line
                     {"ok": true} or {"ok": false, "reason": ..., "error": ...}.
  session file       JSONL. Delivered messages are custom_message entries of customType
                     agent-link; assistant messages carry stopReason; the extension appends a
                     custom entry {"event": "settled"} when a run is over for good.
  Pi renames its process to "pi" ("pi-rpc" in RPC mode); a registry entry whose pid runs anything
  else is stale, and a pane running Pi without an entry lacks the extension. The registry
  directory and the inbox listener must belong to this user, or they are ignored.
docs/adapters/pi.md has the reasons for each choice.
"""

import json
import os
import re
import socket
import stat
import struct
from pathlib import Path

from .. import multiplexers
from ..model import (AWAITING_APPROVAL, NO_INBOX, OK, REFUSED, TIMEOUT, TURN_FAILED, USAGE, AgentRef, LinkError,
                     Receipt)
from ..platform import is_alive
from . import Adapter, program_present

PROTOCOL = 1
CUSTOM_TYPE = "agent-link"
REQUIRED = ("pid", "session_id")
FIELDS = ("protocol", "pid", "session_id", "session_file", "cwd", "socket", "state", "mode", "pi_version")
MAX_LINE_BYTES = 1024 * 1024
FINISHED = ("stop", "length")
FAILED = ("error", "aborted")
PI_TITLE = re.compile(r"^pi(-rpc)?(\s|$)")
NO_EXTENSION = ("Pi without the agent-link extension; restart it with "
                "pi -e <agent-link>/integrations/pi/agent-link.ts, or run install.sh")
REASON_CODES = {"too-large": USAGE, "bad-request": USAGE, "no-session": NO_INBOX, "compacting": REFUSED}


def registry_dirs():
    out = []
    if os.environ.get("XDG_RUNTIME_DIR"):
        out.append(Path(os.environ["XDG_RUNTIME_DIR"]) / "agent-link" / "pi")
    out.append(Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "agent-link" / "pi")
    return out


def private_dir(d):
    try:
        st = d.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077


def registry_entries(dirs):
    out = []
    for d in dirs:
        if not private_dir(d):
            continue
        for f in sorted(d.glob("*.json")):
            try:
                e = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(e, dict) and all(k in e for k in REQUIRED):
                out.append(e)
    return out


def records(path):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def text_of(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def is_inbox(d):
    return d.get("type") == "custom_message" and d.get("customType") == CUSTOM_TYPE


def is_settled(d):
    return (d.get("type") == "custom" and d.get("customType") == CUSTOM_TYPE
            and (d.get("data") or {}).get("event") == "settled")


def message(d, role):
    m = d.get("message") if d.get("type") == "message" else None
    return m if isinstance(m, dict) and m.get("role") == role else None


def entry_text(d):
    """(role, text) a reader cares about, or None."""
    if is_inbox(d):
        return "inbox", text_of(d.get("content"))
    user = message(d, "user")
    if user:
        text = text_of(user.get("content"))
        return ("user", text) if text else None
    m = message(d, "assistant")
    if not m:
        return None
    if m.get("stopReason") in FAILED:
        return "turn", f"{m['stopReason']}: {m.get('errorMessage') or ''}".rstrip(": ")
    text = text_of(m.get("content"))
    if text:
        return "assistant", text
    content = m.get("content") if isinstance(m.get("content"), list) else []
    calls = [b.get("name", "") for b in content if isinstance(b, dict) and b.get("type") == "toolCall"]
    return ("call", ", ".join(calls)) if calls else None


def answer_after(recs, tag):
    """(status, text) for the turn that handled the message carrying tag.

    status: pending (message not in the file yet), running, answered, failed. A stop is not
    final by itself: Pi may retry an error or continue after a stop within the same run, and
    only the settled marker says the run is over. A new input after a finished response ends
    the turn too: a follow-up queued behind this message runs in the same run.
    """
    seen, last, final, finished = False, "", None, False
    for d in recs:
        if not seen:
            seen = is_inbox(d) and tag in text_of(d.get("content"))
            continue
        if is_settled(d) or (finished and (is_inbox(d) or message(d, "user"))):
            if final is None:
                return "failed", "the turn ended without an answer"
            if final.get("stopReason") in FAILED:
                return "failed", final.get("errorMessage") or final["stopReason"]
            return "answered", last
        m = message(d, "assistant")
        if m:
            final, finished = m, m.get("stopReason") in FINISHED
            last = text_of(m.get("content")) or last
    return ("running" if seen else "pending"), last


def deliver(path, text, wait=5.0):
    """(code, detail) of handing text to the extension's inbox socket."""
    wire = json.dumps({"v": PROTOCOL, "type": "message", "text": text}).encode() + b"\n"
    if len(wire) > MAX_LINE_BYTES:
        return USAGE, f"message is {len(wire)} bytes on the wire, cap is {MAX_LINE_BYTES}"
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(wait)
    buf = b""
    try:
        s.connect(path)
        uid = struct.unpack("3i", s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[1]
        if uid != os.getuid():
            return NO_INBOX, f"the listener at {path} runs as uid {uid}, not this user; nothing sent"
        s.sendall(wire)
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    except (FileNotFoundError, ConnectionRefusedError) as e:
        return NO_INBOX, f"no agent-link listener at {path} (Pi exited or unloaded the extension): {e}"
    except TimeoutError:
        return NO_INBOX, f"no acknowledgement from Pi within {wait:g} s; delivery unknown"
    except OSError as e:
        return NO_INBOX, f"inbox socket {path}: {e}"
    finally:
        s.close()
    try:
        reply = json.loads(buf.split(b"\n", 1)[0])
    except ValueError:
        return NO_INBOX, "Pi closed the connection without an acknowledgement; delivery unknown"
    if reply.get("ok") is True:
        return OK, "delivered"
    reason = reply.get("reason", "")
    return REASON_CODES.get(reason, REFUSED), f"{reason}: {reply.get('error', '')}"


class Pi(Adapter):
    kind = "pi"
    can_receive = True
    can_read = True
    reply_detection = True
    subagents = False

    def __init__(self, registry_dir=None):
        self.registry_dir = registry_dir

    def dirs(self):
        return [self.registry_dir] if self.registry_dir else registry_dirs()

    def _ref(self, ctx, d):
        pane = multiplexers.pane_of(d["pid"], ctx.panes, ctx.table)
        sock, session_file = d.get("socket") or "", d.get("session_file") or ""
        if not sock:
            note = f"no inbox: Pi runs in {d.get('mode') or 'a one-shot'} mode"
        elif not session_file:
            note = "no session file (--no-session): send works, read and ask cannot see answers"
        else:
            note = ""
        return AgentRef(
            kind=self.kind, node=ctx.node, instance=d["session_id"],
            session=pane.session if pane else "", position=pane.position if pane else "",
            pane_id=pane.pane_id if pane else "", state=d.get("state") or "unknown",
            cwd=d.get("cwd", ""), title=d.get("name", ""), can_receive=bool(sock), note=note,
            private={"pid": str(d["pid"]), "socket": sock, "session_file": session_file,
                     "version": d.get("pi_version", "")},
        )

    def instances(self, ctx):
        refs = [self._ref(ctx, d) for d in registry_entries(self.dirs()) if runs_pi(ctx, d["pid"])]
        registered = {r.pane_id for r in refs if r.pane_id}
        for pane in ctx.panes:
            if pane.pane_id in registered:
                continue
            pid = next((p for p in ctx.table.descendants(pane.pid) if PI_TITLE.match(ctx.table.args.get(p, ""))), None)
            if pid:
                refs.append(AgentRef(kind=self.kind, node=ctx.node, instance=f"pid-{pid}", session=pane.session,
                                     position=pane.position, pane_id=pane.pane_id, can_receive=False,
                                     note=NO_EXTENSION, private={"pid": pid}))
        return refs

    def whoami(self, ctx, pid, env):
        anc = ctx.table.ancestors(pid)
        mine = [(anc.index(r.private["pid"]), r) for r in self.instances(ctx) if r.private["pid"] in anc]
        if mine:
            return min(mine, key=lambda t: t[0])[1]
        if env.get("PI_SESSION_ID"):
            return AgentRef(kind=self.kind, node=ctx.node, instance=env["PI_SESSION_ID"], can_receive=False,
                            note=NO_EXTENSION)
        return None

    def _session_file(self, ref):
        f = ref.private.get("session_file")
        if not f:
            raise LinkError(NO_INBOX, f"{ref.address}: no session file (--no-session or no extension), "
                                      "nothing to read")
        return f

    def read(self, ctx, ref, limit):
        out = []
        for d in records(self._session_file(ref)):
            got = entry_text(d)
            if got:
                out.append({"time": (d.get("timestamp") or "")[11:19], "role": got[0], "text": got[1]})
        return out[-limit:]

    def send(self, ctx, ref, text):
        if not ref.can_receive:
            raise LinkError(NO_INBOX, f"{ref.address}: {ref.note or 'cannot receive'}")
        code, detail = deliver(ref.private["socket"], text)
        return Receipt(code, detail, instance=ref.instance)

    def poll(self, ctx, ref, message_id):
        pid = ref.private.get("pid")
        alive = is_alive(pid)   # before reading: an answer written before Pi exited is then read too
        status, text = answer_after(records(self._session_file(ref)), message_id)
        if status == "answered":
            return OK, status, text
        if status == "failed":
            return TURN_FAILED, status, f"turn ended with an error: {text}"
        if not alive:
            return TURN_FAILED, "failed", f"Pi (pid {pid}) exited before the turn ended"
        live = next((d for d in registry_entries(self.dirs()) if str(d["pid"]) == pid), None)
        if live and live["session_id"] != ref.instance:
            if status == "pending":
                return TURN_FAILED, "failed", ("Pi left this session (/new, /resume, /fork) before taking "
                                               "the message; it was dropped")
            live = None
        if live and live.get("state") == "awaiting-approval":
            where = f"{ref.session}:{ref.position}" if ref.session else ref.address
            return AWAITING_APPROVAL, "blocked", f"waiting for a dialog in pane {where}: {live.get('prompt') or '?'}"
        return TIMEOUT, status, text

    def doctor(self, ctx):
        dirs = self.dirs()
        if not any(d.exists() for d in dirs) and not program_present(ctx, "pi", PI_TITLE):
            return [(None, f"not found here (no pi on PATH, no pi process, no registry {', '.join(str(d) for d in dirs)})")]
        entries = registry_entries(dirs)
        live = [d for d in entries if runs_pi(ctx, d["pid"])]
        checks = [(False, f"registry {d} is not a private directory of this user; its entries are ignored")
                  for d in dirs if d.exists() and not private_dir(d)]
        checks += [(True, f"registry {', '.join(str(d) for d in dirs)}: {len(live)} live of {len(entries)} entries")]
        for d in live:
            who = f"Pi {d['pid']} (v{d.get('pi_version', '?')})"
            missing = [k for k in FIELDS if k not in d]
            checks.append((d.get("protocol") == PROTOCOL and not missing,
                           f"{who}: extension protocol {d.get('protocol')} (adapter {PROTOCOL})"
                           + (f", missing {missing}" if missing else ", fields ok")))
            if d.get("socket"):
                checks.append((can_connect(d["socket"]), f"{who}: inbox socket {d['socket']} accepts connections"))
            head = records(d.get("session_file") or "")[:1]
            if head:
                ok = head[0].get("type") == "session" and head[0].get("version") == 3
                checks.append((ok, f"{who}: session file header is session version 3 (found {head[0].get('version')})"))
        for r in self.instances(ctx):
            if r.note == NO_EXTENSION:
                checks.append((False, f"Pi in {r.session}:{r.position}: agent-link extension not loaded"))
        return checks


def runs_pi(ctx, pid):
    """The pid is alive and still Pi: a pid freed by a killed Pi may be reused by anything."""
    return bool(PI_TITLE.match(ctx.table.args.get(str(pid), "")))


def can_connect(path):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(2)
    try:
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()
