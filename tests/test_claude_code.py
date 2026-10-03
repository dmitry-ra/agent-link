import unittest
from unittest import mock

from agentlink.adapters import claude_code as cc
from agentlink.model import OK, TIMEOUT, TURN_FAILED
from tests.helpers import S1, ClaudeHome, claude_assistant, claude_enqueue, claude_user, context


class ClaudeCodeAdapter(unittest.TestCase):
    def setUp(self):
        self.home = ClaudeHome()
        self.addCleanup(self.home.tmp.cleanup)
        self.a = cc.ClaudeCode(sessions_dir=self.home.sessions, projects_dir=self.home.projects)
        self.ctx = context()

    def test_instances_only_live_with_tmux_and_inbox(self):
        refs = self.a.instances(self.ctx)
        self.assertEqual([(r.instance, r.session, r.position, r.pane_id, r.can_receive) for r in refs],
                         [(S1, "project-1", "1.1", "%1", True)])
        self.assertEqual(refs[0].private["socket"].endswith("101.sock"), True)

    def test_pane_found_by_process_not_by_registry_pane_id(self):
        # The registry pane id may belong to another tmux server, or the pane may have moved.
        self.home.add_session(101, S1, "renamed:@0.%3", socket="s")
        ref = self.a.instances(self.ctx)[0]
        self.assertEqual((ref.session, ref.pane_id), ("project-1", "%1"))

    def test_non_interactive_session_cannot_receive(self):
        self.home.add_session(101, S1, "project-1:@0.%1", socket="", kind="print")
        self.assertFalse(self.a.instances(self.ctx)[0].can_receive)

    def test_whoami_walks_ancestors(self):
        self.assertEqual(self.a.whoami(self.ctx, "103", {}).instance, S1)
        self.assertIsNone(self.a.whoami(self.ctx, "301", {}))

    def test_split_tmux_keeps_colons_in_session_names(self):
        self.assertEqual(cc.split_tmux("a:b:@3.%12"), ("a:b", "%12"))
        self.assertEqual(cc.split_tmux(""), ("", ""))

    def test_read_shows_text_calls_and_inbox(self):
        self.home.transcript(S1, [claude_user("question"),
                                  {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x"}]}},
                                  claude_enqueue("[agent-link] from a"), claude_assistant("answer")])
        ref = self.a.instances(self.ctx)[0]
        self.assertEqual([(e["role"], e["text"]) for e in self.a.read(self.ctx, ref, 10)],
                         [("user", "question"), ("inbox", "[agent-link] from a"), ("assistant", "answer")])

    def test_answer_after_tag(self):
        old = [claude_user("old"), claude_assistant("WRONG")]
        lines = lambda rows: [__import__("json").dumps(r) for r in rows]
        mine = [claude_enqueue("msg m-abc"), claude_assistant("thinking", stop="tool_use"), claude_assistant("RIGHT")]
        self.assertEqual(cc.answer_after(lines(old), "m-abc"), ("pending", ""))
        self.assertEqual(cc.answer_after(lines(old + mine[:2]), "m-abc"), ("running", "thinking"))
        self.assertEqual(cc.answer_after(lines(old + mine), "m-abc"), ("done", "RIGHT"))
        split = [claude_enqueue("msg m-xyz"), claude_assistant("hmm", msg_id="msg_1", thinking=True),
                 claude_assistant("ANSWER", msg_id="msg_1"), {"type": "system"}]
        self.assertEqual(cc.answer_after(lines(split), "m-xyz"), ("done", "ANSWER"))
        self.assertEqual(cc.answer_after(lines(split[:2]), "m-xyz")[0], "running")

    def test_doctor_names_an_unknown_status_value(self):
        self.home.add_session(101, S1, "project-1:@0.%1", socket="s", status="compacting")
        checks = [(ok, text) for ok, text in self.a.doctor(self.ctx) if "status" in text]
        self.assertTrue(any(ok and "'compacting' is new" in t for ok, t in checks), checks)
        self.home.add_session(101, S1, "project-1:@0.%1", socket="s", status="idle")
        self.assertIn((True, "session 101: status 'idle' known"), self.a.doctor(self.ctx))

    def test_poll_reports_a_recipient_that_exited(self):
        ref = self.a.instances(self.ctx)[0]
        self.home.transcript(S1, [claude_enqueue("msg m-abc"), claude_assistant("thinking", stop="tool_use")])
        with mock.patch.object(cc, "is_alive", return_value=True):
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TIMEOUT, "running"))
        with mock.patch.object(cc, "is_alive", return_value=False):
            code, status, text = self.a.poll(self.ctx, ref, "m-abc")
            self.assertEqual((code, status, "exited" in text), (TURN_FAILED, "failed", True))
            self.home.transcript(S1, [claude_enqueue("msg m-abc"), claude_assistant("RIGHT")])
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc"), (OK, "answered", "RIGHT"))

    def test_poll_reads_liveness_first_and_trusts_a_ref_without_pid(self):
        ref = self.a.instances(self.ctx)[0]
        self.home.transcript(S1, [claude_enqueue("msg m-abc")])

        def answers_then_exits(pid):   # the answer lands between the two reads, then the process is gone
            self.home.transcript(S1, [claude_enqueue("msg m-abc"), claude_assistant("RIGHT")])
            return False

        with mock.patch.object(cc, "is_alive", side_effect=answers_then_exits):
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc"), (OK, "answered", "RIGHT"))
        self.home.transcript(S1, [claude_enqueue("msg m-abc")])
        ref.private.pop("pid")
        with mock.patch.object(cc, "is_alive", return_value=False):
            self.assertEqual(self.a.poll(self.ctx, ref, "m-abc")[:2], (TIMEOUT, "running"))


if __name__ == "__main__":
    unittest.main()
