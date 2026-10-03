import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from agentlink.adapters import codex_cli as cx
from agentlink.model import OK, PAUSED, TIMEOUT
from tests.helpers import (T1, T2, T3, CodexHome, context, cx_ev, cx_meta, cx_msg, fake_codex_on_path, tui_marker,
                           tui_turn)


class CodexCliAdapter(unittest.TestCase):
    def setUp(self):
        self.home = CodexHome()
        self.addCleanup(self.home.tmp.cleanup)
        self.a = cx.CodexCli(home=self.home.root)
        self.ctx = context()
        # T1: an older thread. T2: the thread after /new, with one typed turn. T3: subagent of T2.
        self.home.rollout(T1, [cx_meta(T1, "2026-01-01T00:00:00.000Z"), *cx_msg("user", "first", "cid-1"), cx_ev("task_complete")])
        self.home.rollout(T2, [cx_meta(T2, "2026-01-01T00:01:00.000Z"), cx_ev("task_started"),
                               *cx_msg("developer", "You are Codex"), *cx_msg("user", "# AGENTS.md instructions for /w"),
                               *cx_msg("user", "second", "cid-2"), *cx_msg("assistant", "done"), cx_ev("task_complete")])
        self.home.rollout(T3, [cx_meta(T3, "2026-01-01T00:02:00.000Z", parent=T2), cx_meta(T2), *cx_msg("user", "parent history"),
                               {"type": "inter_agent_communication_metadata", "payload": {}}, cx_ev("task_started"),
                               *cx_msg("assistant", "sub work"), cx_ev("task_complete")])
        os.utime(self.home.log.parent, None)

    def tui(self, log_rows, screen=""):
        self.home.tui_log(log_rows)
        env = {"CODEX_TUI_RECORD_SESSION": "1", "CODEX_TUI_SESSION_LOG_PATH": str(self.home.log)}
        return (mock.patch.object(self.a, "tui_pids", return_value={"%2": ("201", env)}),
                mock.patch("agentlink.multiplexers.screen", return_value=screen))

    def instances(self, log_rows, screen=""):
        p1, p2 = self.tui(log_rows, screen)
        with p1, p2, mock.patch.object(cx, "RECENT", 10 ** 10):
            return self.a.instances(self.ctx)

    def test_binding_follows_new_session_by_client_id(self):
        refs = self.instances([tui_marker("session_start", "2026-01-01T00:00:00.000Z"), tui_turn("cid-1"),
                               tui_marker("new_session", "2026-01-01T00:01:00.000Z"), tui_turn("cid-2")])
        main = [r for r in refs if not r.sub]
        self.assertEqual([(r.instance, r.session, r.state) for r in main], [(T2, "codex-1", "idle")])
        self.assertEqual([(r.sub, r.parent) for r in refs if r.sub], [("helper", T2)])

    def test_binding_by_marker_time_before_any_typed_turn(self):
        refs = self.instances([tui_marker("session_start", "2026-01-01T00:00:01.000Z")])
        self.assertEqual([r.instance for r in refs if not r.sub], [T1])

    def test_new_session_without_typed_turn_moves_binding(self):
        refs = self.instances([tui_marker("session_start", "2026-01-01T00:00:00.000Z"), tui_turn("cid-1"),
                               tui_marker("new_session", "2026-01-01T00:01:01.000Z")])
        self.assertEqual([r.instance for r in refs if not r.sub], [T2])

    def test_resume_binds_by_settings_applied_and_refuses_ambiguity(self):
        resumed = [{"type": "event_msg", "timestamp": "2026-01-01T09:00:00.500Z",
                    "payload": {"type": "thread_settings_applied", "thread_id": T1}}]
        self.home.rollout(T1, [cx_meta(T1, "2026-01-01T00:00:00.000Z"), *cx_msg("user", "first", "cid-1"),
                               cx_ev("task_complete"), *resumed])
        self.assertEqual([r.instance for r in self.instances([tui_marker("session_start", "2026-01-01T09:00:00.000Z")])
                          if not r.sub], [T1])
        self.home.rollout(T2, [cx_meta(T2, "2026-01-01T00:01:00.000Z"), *resumed])
        refs = self.instances([tui_marker("session_start", "2026-01-01T09:00:00.000Z")])
        self.assertEqual([r.can_receive for r in refs if not r.sub], [False])

    def test_unbound_tui_is_listed_but_cannot_receive(self):
        p1, p2 = mock.patch.object(self.a, "tui_pids", return_value={"%2": ("201", {})}), mock.patch("agentlink.multiplexers.screen", return_value="")
        with p1, p2:
            refs = self.a.instances(self.ctx)
        self.assertEqual([(r.session, r.can_receive) for r in refs if not r.sub], [("codex-1", False)])
        self.assertIn("codex-tui.sh", refs[0].note)

    def test_screen_states(self):
        log = [tui_marker("session_start", "2026-01-01T00:01:00.000Z"), tui_turn("cid-2")]
        dialog = "x\n  Would you like to run the following command?\n  $ rm x\n"
        paused = "x\n\u25a0 Conversation interrupted - use /feedback\n\n\u203a Ask Codex"
        self.assertEqual([r.state for r in self.instances(log, dialog) if not r.sub], ["awaiting-approval"])
        self.assertEqual([r.state for r in self.instances(log, paused) if not r.sub], ["paused"])
        self.assertEqual(cx.screen_flags(dialog), (True, False, "rm x"))

    def test_summarize_states(self):
        base = [cx_meta(T1), cx_ev("task_started")]
        cases = [(base, "busy"), (base + [cx_ev("turn_aborted")], "paused"),
                 (base + [cx_ev("task_complete", error={"message": "at capacity"})], "error"), (base + [cx_ev("task_complete")], "idle")]
        for recs, state in cases:
            self.assertEqual(cx.summarize(T1, recs)["state"], state, recs[-1])

    def test_read_hides_injected_and_parent_history(self):
        refs = self.instances([tui_marker("new_session", "2026-01-01T00:01:00.000Z"), tui_turn("cid-2")])
        main = next(r for r in refs if not r.sub)
        sub = next(r for r in refs if r.sub)
        self.assertEqual([e["text"] for e in self.a.read(self.ctx, main, 10) if e["role"] != "turn"], ["second", "done"])
        texts = [e["text"] for e in self.a.read(self.ctx, sub, 10)]
        self.assertIn("sub work", texts)
        self.assertNotIn("parent history", texts)

    def test_answer_after(self):
        recs = [*cx_msg("user", "old"), *cx_msg("assistant", "WRONG"), cx_ev("task_complete"),
                *cx_msg("user", "q m-abc"), *cx_msg("assistant", "RIGHT")]
        self.assertEqual(cx.answer_after(recs[:3], "m-abc"), ("pending", []))
        self.assertEqual(cx.answer_after(recs, "m-abc"), ("running", ["RIGHT"]))
        self.assertEqual(cx.answer_after(recs + [cx_ev("task_complete")], "m-abc"), ("task_complete", ["RIGHT"]))
        self.assertEqual(cx.answer_after(recs + [cx_ev("task_complete", error={"message": "cap"})], "m-abc")[0], "error")

    def test_whoami_by_thread_id(self):
        p1, p2 = self.tui([tui_marker("new_session", "2026-01-01T00:01:00.000Z"), tui_turn("cid-2")])
        with p1, p2, mock.patch.object(cx, "RECENT", 10 ** 10):
            helper = self.a.whoami(self.ctx, "1", {"CODEX_THREAD_ID": T3})
            self.assertEqual((helper.sub, helper.private["pid"]), ("helper", "201"))   # runs in its parent's process
            self.assertEqual(self.a.whoami(self.ctx, "1", {}), None)

    def test_doctor_names_the_first_record_it_found(self):
        with mock.patch.object(cx, "RECENT", 10 ** 10), mock.patch.object(self.a, "tui_pids", return_value={}):
            self.home.rollout(T2, [{"type": "turn_context", "payload": {}}])
            os.utime(self.home.day / f"rollout-2026-01-01T00-00-00-{T2}.jsonl", (2 * 10 ** 9, 2 * 10 ** 9))
            checks = [text for ok, text in self.a.doctor(self.ctx) if not ok]
        self.assertTrue(any("found 'turn_context'" in t for t in checks), checks)

    def test_doctor_reports_a_missing_codex_as_absent(self):
        with tempfile.TemporaryDirectory() as empty, mock.patch.object(cx.shutil, "which", return_value=None):
            self.assertEqual([ok for ok, _ in cx.CodexCli(home=Path(empty)).doctor(self.ctx)], [None])
        with mock.patch.object(cx.shutil, "which", return_value=None), mock.patch.object(self.a, "tui_pids", return_value={}):
            self.assertIn((False, "codex on PATH"), self.a.doctor(self.ctx))   # threads here, binary gone: a fault

    def test_timeout_on_a_never_seen_message_says_so(self):
        with mock.patch.object(self.a, "poll", return_value=(TIMEOUT, "pending", "")):
            code, text = self.a.await_reply(self.ctx, None, "m-abc", 0)
        self.assertEqual((code, "not observed" in text), (TIMEOUT, True))

    def test_send_queues_and_reports_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = fake_codex_on_path(tmp)
            refs = self.instances([tui_marker("new_session", "2026-01-01T00:01:00.000Z"), tui_turn("cid-2")])
            main = next(r for r in refs if not r.sub)
            self.assertEqual(self.a.send(self.ctx, main, "hello").code, OK)
            self.assertEqual(record.read_text().split("\n")[:4], ["queue", "--thread", T2, "--message"])
            main.state = "paused"
            self.assertEqual(self.a.send(self.ctx, main, "hello").code, PAUSED)


if __name__ == "__main__":
    unittest.main()
