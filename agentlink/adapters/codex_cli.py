"""Codex CLI adapter.

Facts it relies on (Codex 0.160; undocumented, checked by doctor()):
  - Threads live in $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<time>-<thread>.jsonl; names in
    $CODEX_HOME/session_index.jsonl. A subagent's rollout starts with a copy of its parent's
    history; its own work begins at the first inter_agent_communication_metadata record.
  - `codex queue --thread <id> --message <text>` hands a message to the shared app-server daemon.
  - Hooks and the shell commands Codex runs execute in that daemon, so their TMUX_PANE is the
    daemon's, not the pane's. A command does get CODEX_THREAD_ID (its own thread).
  - Which thread a TUI pane shows is recorded only by the TUI's own session log, written when the
    TUI starts with CODEX_TUI_RECORD_SESSION=1 and CODEX_TUI_SESSION_LOG_PATH=<file>
    (integrations/codex-tui.sh). The log marks session_start / new_session with timestamps and
    every typed turn with client_user_message_id, which the thread rollout stores as client_id.
  - `resume` writes only session_start to the TUI log; the daemon then appends
    thread_settings_applied to the resumed thread at that moment, which identifies it.
  - A new TUI holds a thread in the daemon, but its rollout file appears only with the first
    message (its name still carries the start time), so an empty TUI is not addressable yet.
  - Approval dialogs are not in the rollout, only on the pane screen. An interrupted turn pauses
    the thread's queue until someone types in the pane.
"""

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import multiplexers
from ..model import AWAITING_APPROVAL, NO_INBOX, OK, PAUSED, TIMEOUT, TURN_FAILED, AgentRef, LinkError, Receipt
from ..platform import environ
from . import Adapter

ID_RE = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")
TURN_END = ("task_complete", "turn_aborted")
TUI_EXCLUDE = (" app-server", " exec", " queue", "code-mode-host", " doctor", " mcp", " login")
RECENT = 24 * 3600
LOG_ENV = "CODEX_TUI_SESSION_LOG_PATH"


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


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


def message_text(payload):
    return "".join(c.get("text", "") for c in payload.get("content") or [] if isinstance(c, dict))


def is_injected(role, text):
    # Codex feeds the model AGENTS.md, skills and environment blocks as messages too.
    return role == "developer" or text.startswith("# AGENTS.md instructions") or text.lstrip().startswith("<")


def turn_error(payload):
    e = payload.get("error")
    return (e.get("message") or json.dumps(e)) if isinstance(e, dict) else (e or "")


def own_records(recs):
    for i, r in enumerate(recs):
        if r.get("type") == "inter_agent_communication_metadata":
            return recs[i:]
    return recs


def summarize(tid, recs):
    """meta and turn state of a thread from its rollout records."""
    meta, started, ended, last_end, error = {}, -1, -1, None, ""
    for i, r in enumerate(recs):
        t, p = r.get("type"), r.get("payload") or {}
        if t == "session_meta" and p.get("id") == tid and not meta:
            meta = p
        elif t == "event_msg" and p.get("type") == "task_started":
            started = i
        elif t == "event_msg" and p.get("type") in TURN_END:
            ended, last_end, error = i, p.get("type"), turn_error(p)
    src = meta.get("source")
    spawn = src.get("subagent", {}).get("thread_spawn", {}) if isinstance(src, dict) else {}
    if started > ended:
        state = "busy"
    elif last_end == "turn_aborted":
        state = "paused"
    elif error:
        state = "error"
    else:
        state = "idle"
    return {"id": tid, "cwd": meta.get("cwd", ""), "started": meta.get("timestamp", ""),
            "parent": spawn.get("parent_thread_id") or "", "agent_path": spawn.get("agent_path") or "",
            "state": state, "error": error if state == "error" else ""}


def transcript(recs):
    out = []
    for r in recs:
        t, p, ts = r.get("type"), r.get("payload") or {}, (r.get("timestamp") or "")[11:19]
        if t == "response_item":
            pt = p.get("type")
            if pt == "message":
                text = message_text(p)
                if not is_injected(p.get("role"), text):
                    out.append({"time": ts, "role": p.get("role"), "text": text})
            elif pt in ("custom_tool_call", "function_call"):
                out.append({"time": ts, "role": "call", "text": f"{p.get('name')}: {p.get('input') or p.get('arguments') or ''}"})
            elif pt in ("custom_tool_call_output", "function_call_output"):
                o = p.get("output")
                out.append({"time": ts, "role": "output", "text": o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)})
        elif t == "event_msg" and p.get("type") in TURN_END:
            err = turn_error(p)
            out.append({"time": ts, "role": "turn", "text": p.get("type") + (f" ERROR: {err}" if err else "")})
    return out


def answer_after(recs, tag):
    """(status, answers): status pending | running | task_complete | turn_aborted | error."""
    seen, answers = False, []
    for r in recs:
        t, p = r.get("type"), r.get("payload") or {}
        if not seen:
            seen = t == "response_item" and p.get("type") == "message" and p.get("role") == "user" and tag in message_text(p)
            continue
        if t == "response_item" and p.get("type") == "message" and p.get("role") == "assistant":
            answers.append(message_text(p))
        elif t == "event_msg" and p.get("type") in TURN_END:
            err = turn_error(p)
            return ("error", answers + [err]) if err else (p.get("type"), answers)
    return ("running" if seen else "pending"), answers


def parse_ts(text):
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def tui_binding(log_lines):
    """From a TUI session log: (marker_time, client_ids since the last session marker)."""
    marker, ids = None, []
    for line in log_lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        kind = d.get("kind")
        if kind in ("session_start", "new_session"):
            marker, ids = parse_ts(d.get("ts", "")), []
        elif kind == "op":
            turn = (d.get("payload") or {}).get("UserTurn")
            if isinstance(turn, dict) and turn.get("client_user_message_id"):
                ids.append(turn["client_user_message_id"])
    return marker, ids


def screen_flags(text):
    lines = [l for l in text.splitlines() if l.strip()]
    dialog = any("Would you like to run" in l or "Would you like to make" in l for l in lines[-25:])
    paused = any("Conversation interrupted" in l for l in lines[-6:])
    cmd = [l.strip()[2:] for l in lines if l.strip().startswith("$ ")]
    return dialog, paused, (cmd[-1] if cmd else "")


class CodexCli(Adapter):
    kind = "codex"
    can_receive = True
    can_read = True
    reply_detection = True
    subagents = True

    def __init__(self, home=None, include_all=False):
        self.home = home
        self.include_all = include_all

    # --- on-disk state -----------------------------------------------------------------

    def _home(self):
        return self.home or codex_home()

    def rollouts(self):
        out = {}
        for f in (self._home() / "sessions").glob("*/*/*/rollout-*.jsonl"):
            m = ID_RE.search(f.name)
            if m:
                out[m.group(1)] = f
        return out

    def names(self):
        names = {}
        path = self._home() / "session_index.jsonl"
        for d in records(path):
            if d.get("id"):
                names[d["id"]] = d.get("thread_name") or ""
        return names

    def bind(self, log_path, rollouts):
        """Thread shown by the TUI that writes log_path, or None."""
        try:
            lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        marker, ids = tui_binding(lines)
        if marker is None:
            return None
        fresh = sorted(((f.stat().st_mtime, tid, f) for tid, f in rollouts.items() if f.stat().st_mtime >= marker - 5), reverse=True)
        if ids:
            needle = f'"client_id":"{ids[-1]}"'
            for _, tid, f in fresh:
                try:
                    if needle in f.read_text(encoding="utf-8", errors="replace"):
                        return tid
                except OSError:
                    continue
        # No typed turn yet in this thread. A new thread (start, /new) has session_meta at the
        # marker time; a resumed one gets thread_settings_applied at that time. Bind only when
        # exactly one thread matches: a coincidence with another thread's turn stays unbound.
        found = set()
        for _, tid, f in fresh:
            for r in records(f):
                t, p = r.get("type"), r.get("payload") or {}
                if t == "session_meta" and p.get("id") == tid:
                    src = p.get("source")
                    if isinstance(src, dict) and src.get("subagent"):
                        break
                    when = parse_ts(p.get("timestamp", ""))
                elif t == "event_msg" and p.get("type") == "thread_settings_applied":
                    when = parse_ts(r.get("timestamp", ""))
                else:
                    continue
                if when is not None and abs(when - marker) <= 3:
                    found.add(tid)
                    break
        return found.pop() if len(found) == 1 else None

    def tui_pids(self, ctx):
        """{pane_id: (pid, env)} for panes running a Codex TUI."""
        out = {}
        for pane in ctx.panes:
            for pid in ctx.table.descendants(pane.pid):
                args = ctx.table.args.get(pid, "")
                if re.search(r"(^|/)codex(\s|$)", args) and not any(x in args for x in TUI_EXCLUDE):
                    env = environ(pid)
                    if pane.pane_id not in out or env.get(LOG_ENV):
                        out[pane.pane_id] = (pid, env)
        return out

    # --- adapter interface -------------------------------------------------------------

    def instances(self, ctx):
        rollouts, names = self.rollouts(), self.names()
        refs, bound = [], set()
        for pane_id, (pid, env) in self.tui_pids(ctx).items():
            pane = ctx.pane_by_id[pane_id]
            log = env.get(LOG_ENV) if env.get("CODEX_TUI_RECORD_SESSION") == "1" else None
            tid = self.bind(log, rollouts) if log else None
            dialog, paused, _ = screen_flags(multiplexers.screen(pane))
            if not tid:
                note = ("Codex here was not started with a session log; restart it with integrations/codex-tui.sh"
                        if not log else "no thread on disk yet: Codex writes it with the first message typed in this pane")
                refs.append(AgentRef(kind=self.kind, node=ctx.node, instance=f"tui-{pid}", session=pane.session,
                                     position=pane.position, pane_id=pane_id, can_receive=False, note=note,
                                     state="awaiting-approval" if dialog else "unknown", private={"pid": pid}))
                continue
            bound.add(tid)
            s = summarize(tid, records(rollouts[tid]))
            state = "awaiting-approval" if dialog else "paused" if paused or s["state"] == "paused" else s["state"]
            refs.append(AgentRef(kind=self.kind, node=ctx.node, instance=tid, session=pane.session,
                                 position=pane.position, pane_id=pane_id, state=state, cwd=s["cwd"],
                                 title=names.get(tid, ""), note=s["error"], private={"pid": pid, "log": log}))
        now = time.time()
        for tid, f in rollouts.items():
            if tid in bound or now - f.stat().st_mtime > RECENT:
                continue
            s = summarize(tid, records(f))
            if s["parent"] and s["parent"] in bound:
                parent = next(r for r in refs if r.instance == s["parent"])
                refs.append(AgentRef(kind=self.kind, node=ctx.node, instance=tid, sub=s["agent_path"].removeprefix("/root/"),
                                     parent=s["parent"], session=parent.session, position=parent.position,
                                     pane_id=parent.pane_id, state=s["state"], cwd=s["cwd"], note=s["error"],
                                     private={"pid": parent.private.get("pid")}))
            elif self.include_all and not s["parent"]:
                refs.append(AgentRef(kind=self.kind, node=ctx.node, instance=tid, state=s["state"], cwd=s["cwd"],
                                     title=names.get(tid, ""), note="not shown in any pane"))
        return refs

    def whoami(self, ctx, pid, env):
        tid = env.get("CODEX_THREAD_ID")
        if not tid:
            return None
        for ref in self.instances(ctx):
            if ref.instance == tid:
                return ref
        return AgentRef(kind=self.kind, node=ctx.node, instance=tid, note="thread not shown in any pane")

    def _rollout(self, ref):
        f = self.rollouts().get(ref.instance)
        if not f:
            raise LinkError(NO_INBOX, f"no rollout for thread {ref.instance}")
        return f

    def read(self, ctx, ref, limit):
        recs = records(self._rollout(ref))
        return transcript(own_records(recs) if ref.sub else recs)[-limit:]

    def send(self, ctx, ref, text):
        if not ref.can_receive:
            raise LinkError(NO_INBOX, f"{ref.address}: {ref.note or 'cannot receive'}")
        if not shutil.which("codex"):
            raise LinkError(NO_INBOX, "codex is not on PATH")
        p = subprocess.run(["codex", "queue", "--thread", ref.instance, "--message", text],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            return Receipt(NO_INBOX, "codex queue failed: " + (p.stderr or p.stdout).strip(), instance=ref.instance)
        if ref.state == "paused":
            return Receipt(PAUSED, f"queued, but the thread is paused after an interrupted turn: it runs only after "
                                   f"someone types in pane {ref.session}:{ref.position} (type something neutral; "
                                   "'continue' makes Codex retry the interrupted step)", instance=ref.instance)
        return Receipt(OK, "queued", instance=ref.instance)

    def poll(self, ctx, ref, message_id):
        status, answers = answer_after(records(self._rollout(ref)), message_id)
        if status == "task_complete":
            return OK, "answered", answers[-1] if answers else ""
        if status in ("error", "turn_aborted"):
            return TURN_FAILED, "failed", f"turn ended with {status}: {answers[-1] if answers else ''}"
        pane = ctx.pane_by_id.get(ref.pane_id)
        if pane:
            dialog, paused, cmd = screen_flags(multiplexers.screen(pane))
            if dialog:
                return AWAITING_APPROVAL, "blocked", f"waiting for an approval dialog in pane {pane.session}:{pane.position}: {cmd}"
            if paused and status == "pending":
                return PAUSED, "blocked", f"thread paused; type in pane {pane.session}:{pane.position} to resume its queue"
        return TIMEOUT, status, ""

    def await_reply(self, ctx, ref, message_id, timeout):
        # Screen states are trusted only after a grace period: a dialog seen at once may belong
        # to an earlier turn that is about to be answered by the human.
        deadline, grace = time.time() + timeout, time.time() + 20
        while True:
            code, status, text = self.poll(ctx, ref, message_id)
            if status in ("answered", "failed") or (status == "blocked" and time.time() > grace):
                return code, text
            if time.time() >= deadline:
                return TIMEOUT, f"no answer to {message_id} within {timeout}s (status {status})"
            time.sleep(2)

    def doctor(self, ctx):
        checks = [(shutil.which("codex") is not None, "codex on PATH")]
        home = self._home()
        checks.append(((home / "sessions").is_dir(), f"thread store {home / 'sessions'}"))
        rollouts = self.rollouts()
        if rollouts:
            newest = max(rollouts.values(), key=lambda f: f.stat().st_mtime)
            first = records(newest)[:1]
            ok = bool(first) and first[0].get("type") == "session_meta"
            checks.append((ok, f"rollout format: first record is session_meta ({newest.name[:40]}...)"))
        for pane_id, (pid, env) in self.tui_pids(ctx).items():
            pane = ctx.pane_by_id[pane_id]
            has = env.get("CODEX_TUI_RECORD_SESSION") == "1" and env.get(LOG_ENV)
            checks.append((bool(has), f"Codex TUI in {pane.session}:{pane.position}: "
                                      + ("session log on, addressable" if has else "no session log - restart it with integrations/codex-tui.sh")))
        return checks
