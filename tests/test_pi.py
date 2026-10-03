import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agentlink.adapters import Context, pi
from agentlink.platform.linux import ProcessTable
from agentlink.model import AWAITING_APPROVAL, NO_INBOX, OK, REFUSED, TIMEOUT, TURN_FAILED, USAGE
from tests.helpers import (P1, P3, PiHome, pi_assistant, pi_context, pi_inbox, pi_settled, pi_tool_result, pi_user)

ROOT = Path(__file__).resolve().parent.parent


class FakeInbox:
    """A unix socket listener that records the line it gets and answers as told."""

    def __init__(self, path, answer):
        self.lines = []
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(1)
        self.thread = threading.Thread(target=self._serve, args=(answer,), daemon=True)
        self.thread.start()

    def _serve(self, answer):
        conn, _ = self.server.accept()
        with conn:
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
            self.lines.append(buf)
            if answer is not None:
                conn.sendall(answer)

    def close(self):
        self.thread.join(5)
        self.server.close()


class PiAdapter(unittest.TestCase):
    def setUp(self):
        self.home = PiHome()
        self.addCleanup(self.home.tmp.cleanup)
        self.a = pi.Pi(registry_dir=self.home.registry)
        self.ctx = pi_context()

    def ref(self, sid=P1):
        return next(r for r in self.a.instances(self.ctx) if r.instance == sid)

    def test_instances_live_entries_inbox_and_missing_extension(self):
        self.home.add(301, "s-reused")   # a killed Pi's pid now runs vim
        refs = self.a.instances(self.ctx)
        self.assertEqual([(r.instance, r.session, r.can_receive, r.title) for r in refs],
                         [(P1, "pi-1", True, "n401"), (P3, "pi-1", False, "n404"), ("pid-501", "pi-2", False, "")])
        self.assertIn("print mode", refs[1].note)
        self.assertEqual(refs[2].note, pi.NO_EXTENSION)

    def test_doctor_absent_only_without_any_trace_of_pi(self):
        nowhere = pi.Pi(registry_dir=self.home.root / "nowhere")
        bare = Context("node1", ProcessTable([("1", "0", "init")]), [])
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual([ok for ok, _ in nowhere.doctor(bare)], [None])
            self.assertNotIn(None, [ok for ok, _ in nowhere.doctor(self.ctx)])   # pi processes run here

    def test_shared_registry_directory_is_ignored(self):
        self.home.registry.chmod(0o755)
        self.assertEqual(pi.registry_entries([self.home.registry]), [])
        self.assertIn((False, f"registry {self.home.registry} is not a private directory of this user; "
                              "its entries are ignored"), self.a.doctor(self.ctx))

    def test_whoami_nearest_pi_ancestor_then_session_variable(self):
        self.assertEqual(self.a.whoami(self.ctx, "403", {}).instance, P1)
        self.assertEqual(self.a.whoami(self.ctx, "405", {"PI_SESSION_ID": P1}).instance, P3)
        self.assertEqual(self.a.whoami(self.ctx, "502", {}).note, pi.NO_EXTENSION)
        outside = self.a.whoami(self.ctx, "301", {"PI_SESSION_ID": "s-9"})
        self.assertEqual((outside.instance, outside.can_receive), ("s-9", False))
        self.assertIsNone(self.a.whoami(self.ctx, "301", {}))

    def test_read_shows_conversation_not_internals(self):
        self.home.session(P1, [{"type": "message", "message": {"role": "system", "content": "prompt"}},
                               pi_user("question"), pi_assistant("let me look", stop="toolUse", calls=["bash"]),
                               pi_tool_result("output"), pi_assistant(stop="toolUse", calls=["read", "bash"]),
                               pi_inbox("[agent-link] from a"), pi_inbox("other", custom_type="x"),
                               pi_assistant("partial", stop="error", error="overloaded"), pi_assistant("answer"),
                               pi_settled()])
        self.assertEqual([(e["role"], e["text"]) for e in self.a.read(self.ctx, self.ref(), 20)],
                         [("user", "question"), ("assistant", "let me look"), ("call", "read, bash"),
                          ("inbox", "[agent-link] from a"), ("turn", "error: overloaded"), ("assistant", "answer")])

    def test_answer_after(self):
        q = pi_inbox("[agent-link] ... id m-abc ...")
        cases = [
            ("not delivered yet", [pi_user("x"), pi_assistant("WRONG"), pi_settled()], ("pending", "")),
            ("tool call under way", [q, pi_assistant("looking", stop="toolUse", calls=["bash"])], ("running", "looking")),
            ("stop is not final before settle", [q, pi_assistant("first")], ("running", "first")),
            ("answer split by a tool call", [q, pi_assistant("looking", stop="toolUse", calls=["bash"]),
                                             pi_tool_result("4"), pi_assistant("RIGHT"), pi_settled()], ("answered", "RIGHT")),
            ("retried error is not a failure", [q, pi_assistant(stop="error", error="overloaded"),
                                                {"type": "context_edit", "targetId": "x", "replacement": None},
                                                pi_assistant("RIGHT"), pi_settled()], ("answered", "RIGHT")),
            ("continuation after stop", [q, pi_assistant("draft"), pi_inbox("check again", custom_type="x"),
                                         pi_assistant("RIGHT"), pi_settled()], ("answered", "RIGHT")),
            ("next queued message in the same run", [q, pi_assistant("RIGHT"), pi_inbox("[agent-link] id m-def"),
                                                     pi_assistant("WRONG"), pi_settled()], ("answered", "RIGHT")),
            ("human types after the answer", [q, pi_assistant("RIGHT"), pi_user("thanks"), pi_assistant("WRONG"),
                                              pi_settled()], ("answered", "RIGHT")),
            ("human steers mid-turn", [q, pi_assistant(stop="toolUse", calls=["bash"]), pi_tool_result("x"),
                                       pi_user("also say hi"), pi_assistant("RIGHT"), pi_settled()], ("answered", "RIGHT")),
            ("aborted", [q, pi_assistant("half", stop="aborted"), pi_settled()], ("failed", "aborted")),
            ("retries exhausted", [q, pi_assistant(stop="error", error="cap"), pi_settled()], ("failed", "cap")),
            ("settled with no response", [q, pi_settled()], ("failed", "the turn ended without an answer")),
            ("an earlier message and its answer", [pi_inbox("[agent-link] ... id m-old ..."), pi_assistant("WRONG"),
                                                   pi_settled(), q, pi_assistant("RIGHT"), pi_settled()],
             ("answered", "RIGHT")),
            ("other custom entries mid-turn", [q, pi_assistant("looking", stop="toolUse", calls=["bash"]),
                                               {"type": "custom", "customType": "model-state", "data": {}},
                                               {"type": "custom", "customType": "agent-link", "data": {"event": "x"}},
                                               pi_tool_result("4"), pi_assistant("RIGHT"), pi_settled()],
             ("answered", "RIGHT")),
        ]
        for name, recs, want in cases:
            with self.subTest(name):
                self.assertEqual(pi.answer_after(recs, "m-abc"), want)

    def test_send_through_the_inbox_socket(self):
        cases = [
            ("delivered", b'{"ok": true}\n', OK, "delivered"),
            ("refused while compacting", b'{"ok": false, "reason": "compacting", "error": "busy"}\n', REFUSED, "compacting"),
            ("no acknowledgement", None, NO_INBOX, "delivery unknown"),
        ]
        for name, answer, code, word in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "s.sock"
                inbox = FakeInbox(path, answer)
                got = pi.deliver(str(path), "hello\nworld")
                inbox.close()
                self.assertEqual((got[0], word in got[1]), (code, True), got)
                self.assertEqual(json.loads(inbox.lines[0]), {"v": 1, "type": "message", "text": "hello\nworld"})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pi.os, "getuid", return_value=os.getuid() + 1):
            path = Path(tmp) / "s.sock"
            inbox = FakeInbox(path, None)
            code, detail = pi.deliver(str(path), "secret")
            inbox.close()
            self.assertEqual((code, "nothing sent" in detail, inbox.lines), (NO_INBOX, True, [b""]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.sock"
            self.assertEqual(pi.deliver(str(path), "x")[0], NO_INBOX)
            inbox = FakeInbox(path, b'{"ok": true}\n')
            self.assertEqual(pi.deliver(str(path), "x" * pi.MAX_LINE_BYTES)[0], USAGE)
            pi.deliver(str(path), "x")   # the listener must see only this one
            inbox.close()
            self.assertEqual(json.loads(inbox.lines[0])["text"], "x")

    def test_poll_reports_dialog_exit_and_answer(self):
        self.home.session(P1, [pi_inbox("id m-abc"), pi_assistant(stop="toolUse", calls=["bash"])])
        ref = self.ref()
        with mock.patch.object(pi, "is_alive", return_value=True):
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TIMEOUT, "running"))
            self.home.add(401, P1, socket="s", state="awaiting-approval", prompt="Allow sudo?")
            code, status, text = self.a.poll(self.ctx, ref, "m-abc")
            self.assertEqual((code, status, "pi-1:1.1" in text and "Allow sudo?" in text), (AWAITING_APPROVAL, "blocked", True))
        with mock.patch.object(pi, "is_alive", return_value=False):
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TURN_FAILED, "failed"))
            self.home.session(P1, [pi_inbox("id m-abc"), pi_assistant("4"), pi_settled()])
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc"), (OK, "answered", "4"))
            self.home.session(P1, [pi_inbox("id m-abc"), pi_assistant(stop="error", error="cap"), pi_settled()])
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TURN_FAILED, "failed"))

    def test_poll_message_dropped_by_a_session_switch(self):
        self.home.session(P1, [pi_user("busy")])
        ref = self.ref()
        with mock.patch.object(pi, "is_alive", return_value=True):
            (self.home.registry / "401.json").unlink()   # between /reload's shutdown and start
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TIMEOUT, "pending"))
            self.home.add(401, "01a0fe18-0009-7000-8000-000000000009", socket="s")   # /new dropped the queue
            code, status, text = self.a.poll(self.ctx, ref, "m-abc")
            self.assertEqual((code, status, "dropped" in text), (TURN_FAILED, "failed", True))


def typescript_node():
    node = shutil.which("node")
    if not node:
        return None
    p = subprocess.run([node, "-p", "process.features.typescript || ''"], capture_output=True, text=True)
    return node if p.stdout.strip() else None


@unittest.skipUnless(typescript_node(), "needs node that runs TypeScript (22.18+)")
class PiExtension(unittest.TestCase):
    """integrations/pi/agent-link.ts against a fake Pi API, through its real socket."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        pkg = self.root / "node_modules" / "@earendil-works" / "pi-coding-agent"
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text('{"name": "@earendil-works/pi-coding-agent", "type": "module", "main": "index.js"}')
        (pkg / "index.js").write_text('export const VERSION = "0.0.0-test";\n')
        shutil.copy(ROOT / "integrations" / "pi" / "agent-link.ts", self.root / "agent-link.ts")
        self.runtime = self.root / "run"
        self.runtime.mkdir(mode=0o700)
        self.proc = subprocess.Popen([typescript_node(), str(ROOT / "tests" / "pi_extension_harness.mjs"),
                                      str(self.root / "agent-link.ts")], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True, env={**os.environ, "XDG_RUNTIME_DIR": str(self.runtime)})
        self.addCleanup(self.proc.stdout.close)
        self.addCleanup(self.proc.wait, 10)
        self.addCleanup(self.proc.stdin.close)
        self.dir = self.runtime / "agent-link" / "pi"

    def do(self, **cmd):
        self.proc.stdin.write(json.dumps(cmd) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def entry(self):
        return json.loads((self.dir / f"{self.proc.pid}.json").read_text())

    def raw(self, data):
        """Write data to the inbox, close the writing side, return what comes back."""
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(5)
        s.connect(str(self.dir / f"{self.proc.pid}.sock"))
        s.sendall(data)
        s.shutdown(socket.SHUT_WR)
        out = b""
        while chunk := s.recv(4096):
            out += chunk
        s.close()
        return out

    def test_registry_inbox_and_settled_marker(self):
        self.assertTrue(self.do(load=2)["ok"])   # loaded twice: the first copy serves
        self.assertTrue(self.do(emit="session_start", event={"reason": "startup"})["ok"])
        e = self.entry()
        self.assertEqual({k: e[k] for k in ("protocol", "session_id", "session_file", "state", "mode", "pi_version")},
                         {"protocol": 1, "session_id": "s-1", "session_file": "/w/s-1.jsonl", "state": "idle",
                          "mode": "tui", "pi_version": "0.0.0-test"})
        self.assertEqual(self.dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(e["socket"]).st_mode & 0o777, 0o600)

        self.assertEqual(pi.deliver(e["socket"], "hello"), (OK, "delivered"))
        self.assertEqual(self.do(log=True)["log"],
                         [{"copy": 0, "sent": {"customType": "agent-link", "content": "hello", "display": True},
                           "options": {"triggerTurn": True, "deliverAs": "followUp"}}])

        self.do(emit="agent_start")
        self.assertEqual(self.entry()["state"], "busy")
        self.do(emit="ui_prompt_start", event={"kind": "confirm", "title": "Allow?"})
        self.assertEqual((self.entry()["state"], self.entry()["prompt"]), ("awaiting-approval", "Allow?"))
        self.do(emit="ui_prompt_end", event={"kind": "confirm"})
        self.do(set={"name": "work"}, emit="agent_settled")
        self.assertEqual((self.entry()["state"], self.entry()["name"]), ("idle", "work"))
        self.do(set={"name": "renamed"}, emit="session_info_changed")
        self.assertEqual(self.entry()["name"], "renamed")
        self.assertEqual(self.do(log=True)["log"], [{"copy": 0, "entry": {"customType": "agent-link", "data": {"event": "settled"}}}])

        self.do(emit="session_shutdown", event={"reason": "quit"})
        self.assertEqual(sorted(self.dir.iterdir()), [])

    def test_inbox_fails_closed(self):
        self.do(load=1)
        self.do(emit="session_start", event={"reason": "startup"})
        cases = [
            ("half a line", b'{"v": 1, "type": "message", "text": "half"}', b""),
            ("not JSON", b"hello\n", b"bad-request"),
            ("empty text", b'{"v": 1, "type": "message", "text": " "}\n', b"bad-request"),
            ("other protocol", b'{"v": 2, "type": "message", "text": "x"}\n', b"bad-request"),
            ("too long", b"x" * (pi.MAX_LINE_BYTES + 2), b"too-large"),
        ]
        for name, data, want in cases:
            with self.subTest(name):
                self.assertIn(want, self.raw(data))
        self.do(set={"idle": False})   # no run, not idle: a manual /compact
        self.assertEqual(pi.deliver(self.entry()["socket"], "x")[0], REFUSED)
        self.assertEqual(self.do(log=True)["log"], [])

    def test_entry_not_written_through_a_link(self):
        self.dir.mkdir(parents=True, mode=0o700)
        target = self.root / "victim"
        target.write_text("keep")
        (self.dir / f"{self.proc.pid}.json.tmp").symlink_to(target)
        self.do(load=1)
        self.assertTrue(self.do(emit="session_start", event={"reason": "startup"})["ok"])
        self.assertEqual((target.read_text(), self.entry()["session_id"]), ("keep", "s-1"))

    def test_shared_directory_is_refused(self):
        self.dir.mkdir(parents=True, mode=0o755)
        self.dir.chmod(0o755)
        self.do(load=1)
        r = self.do(emit="session_start", event={"reason": "startup"})
        self.assertEqual((r["ok"], "not a private directory" in r.get("error", "")), (False, True))
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
