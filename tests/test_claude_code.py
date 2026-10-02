import unittest

from agentlink.adapters import claude_code as cc
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


if __name__ == "__main__":
    unittest.main()
