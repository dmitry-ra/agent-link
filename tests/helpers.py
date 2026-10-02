"""Synthetic fixtures shaped like the real on-disk formats. No real conversations, paths or ids."""

import json
import os
import tempfile
from pathlib import Path

from agentlink.adapters import Context
from agentlink.multiplexers import Pane
from agentlink.platform.linux import ProcessTable

T1 = "11111111-1111-7111-8111-111111111111"   # codex main thread
T2 = "22222222-2222-7222-8222-222222222222"   # codex thread after /new
T3 = "33333333-3333-7333-8333-333333333333"   # codex subagent of T2
S1 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"   # claude session
S2 = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def panes():
    return [Pane("tmux", "project-1", "1.1", "%1", "100", "/w"),
            Pane("tmux", "codex-1", "1.1", "%2", "200", "/w"),
            Pane("tmux", "shell-1", "1.1", "%3", "300", "/w")]


def table():
    # 100 -> claude 101 -> bash 102 -> agent-link 103 ; 200 -> codex tui 201 ; 300 -> bash 301
    rows = [("1", "0", "init"), ("100", "1", "bash"), ("101", "100", "claude"), ("102", "101", "bash -c x"),
            ("103", "102", "python3 bin/agent-link whoami"), ("200", "1", "bash"),
            ("201", "200", "node /x/bin/codex"), ("300", "1", "bash"), ("301", "300", "vim")]
    return ProcessTable(rows)


def context():
    return Context("node1", table(), panes(), hop_limit=3)


class ClaudeHome:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.projects = self.root / "projects"
        self.sessions.mkdir()
        self.add_session(101, S1, "project-1:@0.%1", socket=str(self.root / "101.sock"))
        self.add_session(999, S2, "gone:@0.%9", socket=str(self.root / "999.sock"))   # pid not running
        (self.sessions / "101.deadbeef.key").write_text("secret")

    def add_session(self, pid, sid, tmux, socket="", kind="interactive", status="idle"):
        d = {"pid": pid, "sessionId": sid, "cwd": "/w", "tmux": tmux, "messagingSocketPath": socket,
             "status": status, "kind": kind, "name": f"n{pid}", "version": "2.1.285"}
        (self.sessions / f"{pid}.json").write_text(json.dumps(d))

    def transcript(self, sid, rows):
        write_jsonl(self.projects / "-w" / f"{sid}.jsonl", rows)


def claude_user(text):
    return {"type": "user", "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "user", "content": text}}


def claude_assistant(text, stop="end_turn", msg_id=None, thinking=False):
    block = {"type": "thinking", "thinking": text} if thinking else {"type": "text", "text": text}
    return {"type": "assistant", "timestamp": "2026-01-01T00:00:02Z",
            "message": {"id": msg_id or f"msg_{abs(hash(text)) % 10**8}", "role": "assistant", "content": [block], "stop_reason": stop}}


def claude_enqueue(text):
    return {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-01-01T00:00:03Z", "content": text}


class CodexHome:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.day = self.root / "sessions" / "2026" / "01" / "01"
        self.log = self.root / "tui.jsonl"

    def rollout(self, tid, rows, start="2026-01-01T00:00:00.000Z"):
        f = self.day / f"rollout-2026-01-01T00-00-00-{tid}.jsonl"
        write_jsonl(f, rows)
        return f

    def tui_log(self, rows):
        write_jsonl(self.log, rows)


def cx_meta(tid, ts="2026-01-01T00:00:00.000Z", parent=None):
    src = {"subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_path": "/root/helper"}}} if parent else "vscode"
    return {"type": "session_meta", "payload": {"id": tid, "cwd": "/w", "timestamp": ts, "source": src}}


def cx_msg(role, text, client_id=None):
    p = {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}
    row = {"type": "response_item", "timestamp": "2026-01-01T00:00:05Z", "payload": p}
    if client_id:
        return [row, {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "client_id": client_id}}}]
    return [row]


def cx_ev(kind, **kw):
    return {"type": "event_msg", "timestamp": "2026-01-01T00:00:09Z", "payload": {"type": kind, **kw}}


def tui_marker(kind, ts):
    return {"ts": ts, "dir": "meta" if kind == "session_start" else "to_tui", "kind": kind}


def tui_turn(client_id):
    return {"ts": "2026-01-01T00:00:04.000Z", "dir": "from_tui", "kind": "op",
            "payload": {"UserTurn": {"client_user_message_id": client_id, "items": []}}}


def fake_codex_on_path(tmpdir):
    """A `codex` executable that records its arguments; returns the record file."""
    bin_dir = Path(tmpdir) / "bin"
    bin_dir.mkdir(exist_ok=True)
    record = Path(tmpdir) / "codex-args.txt"
    script = bin_dir / "codex"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {record}\necho queued\n")
    script.chmod(0o755)
    os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
    return record


P1 = "01a0fe18-0001-7000-8000-000000000001"   # pi session, tui
P2 = "01a0fe18-0002-7000-8000-000000000002"   # pi session of a dead process
P3 = "01a0fe18-0003-7000-8000-000000000003"   # pi -p started from inside P1


def pi_context():
    panes_ = [Pane("tmux", "pi-1", "1.1", "%4", "400", "/w"), Pane("tmux", "pi-2", "1.1", "%5", "500", "/w"),
              Pane("tmux", "shell-1", "1.1", "%3", "300", "/w")]
    # 400 -> pi 401 -> bash 402 -> agent-link 403, and 402 -> pi -p 404 -> bash 405 ;
    # 500 -> pi 501 (no extension) -> bash 502 ; 300 -> vim 301
    rows = [("1", "0", "init"), ("400", "1", "bash"), ("401", "400", "pi"), ("402", "401", "bash -c x"),
            ("403", "402", "python3 bin/agent-link whoami"), ("404", "402", "pi -p hello"), ("405", "404", "bash -c y"),
            ("500", "1", "bash"), ("501", "500", "pi"), ("502", "501", "bash -c z"), ("300", "1", "bash"),
            ("301", "300", "vim")]
    return Context("node1", ProcessTable(rows), panes_, hop_limit=3)


class PiHome:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = self.root / "agent-link" / "pi"
        self.registry.mkdir(parents=True)
        self.registry.chmod(0o700)
        self.add(401, P1, socket=str(self.root / "401.sock"))
        self.add(999, P2, socket=str(self.root / "999.sock"))
        self.add(404, P3, mode="print", session_file="")

    def add(self, pid, sid, socket="", mode="tui", state="idle", prompt="", session_file=None):
        d = {"protocol": 1, "pid": pid, "session_id": sid,
             "session_file": str(self.root / f"{sid}.jsonl") if session_file is None else session_file,
             "cwd": "/w", "name": f"n{pid}", "socket": socket, "state": state, "prompt": prompt, "mode": mode,
             "pi_version": "1.0.0"}
        (self.registry / f"{pid}.json").write_text(json.dumps(d))

    def session(self, sid, rows):
        write_jsonl(self.root / f"{sid}.jsonl", [{"type": "session", "version": 3, "id": sid, "cwd": "/w"}] + rows)


def pi_user(text):
    return {"type": "message", "timestamp": "2026-01-01T00:00:01.000Z", "message": {"role": "user", "content": text}}


def pi_assistant(text="", stop="stop", calls=(), error=None):
    content = ([{"type": "thinking", "thinking": "hmm"}] + ([{"type": "text", "text": text}] if text else [])
               + [{"type": "toolCall", "id": f"c{i}", "name": n, "arguments": {}} for i, n in enumerate(calls)])
    m = {"role": "assistant", "content": content, "stopReason": stop}
    if error:
        m["errorMessage"] = error
    return {"type": "message", "timestamp": "2026-01-01T00:00:02.000Z", "message": m}


def pi_tool_result(text):
    return {"type": "message", "message": {"role": "toolResult", "toolName": "bash", "content": [{"type": "text", "text": text}]}}


def pi_inbox(text, custom_type="agent-link"):
    return {"type": "custom_message", "timestamp": "2026-01-01T00:00:03.000Z", "customType": custom_type,
            "content": text, "display": True}


def pi_settled():
    return {"type": "custom", "customType": "agent-link", "data": {"event": "settled"}}
