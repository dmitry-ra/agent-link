import contextlib
import io
import random
import unittest
from unittest import mock

from agentlink import address, cli, envelope, rpc
from agentlink.adapters import Adapter, Context
from agentlink.multiplexers import Pane
from agentlink.platform.linux import ProcessTable
from agentlink.model import NO_INBOX, REFUSED, TIMEOUT, USAGE, AgentRef, LinkError


def ref(kind, instance, session="", position="", sub="", parent=""):
    return AgentRef(kind=kind, node="n", instance=instance, session=session, position=position, sub=sub, parent=parent)


class Addresses(unittest.TestCase):
    def test_parse_every_documented_form(self):
        cases = {
            "project-1": ("project-1", "", "", "", "", ""),
            "project-1:2.1": ("project-1", "2.1", "", "", "", ""),
            "codex-1/reviewer": ("codex-1", "", "", "", "reviewer", ""),
            "codex#9f3a1c2e": ("", "", "codex", "9f3a1c2e", "", ""),
            "codex#9f3a1c2e/helper@vm": ("", "", "codex", "9f3a1c2e", "helper", "vm"),
            "project-1@box": ("project-1", "", "", "", "", "box"),
        }
        for text, want in cases.items():
            a = address.parse(text)
            self.assertEqual((a.session, a.position, a.kind, a.ident, a.sub, a.node), want, text)

    def test_parse_rejects(self):
        for bad, why in (("", "not an agent"), ("a b", "not an agent"), ("codex#01a", "too short"), ("x:1", "not an agent")):
            with self.assertRaises(LinkError) as c:
                address.parse(bad)
            self.assertEqual(c.exception.code, USAGE)
            self.assertIn(why, str(c.exception))

    def test_assign_and_resolve(self):
        refs = address.assign([
            ref("claude", "c1", "solo", "1.1"),
            ref("claude", "c2", "shared", "1.1"), ref("codex", "x1", "shared", "2.1"),
            ref("codex", "x9abcdef", ""),
            ref("codex", "x2", "shared", "2.1", sub="helper", parent="x1"),
        ])
        self.assertEqual([r.address for r in refs], ["solo", "shared:1.1", "shared:2.1", "codex#x9abcdef", "shared:2.1/helper"])
        self.assertEqual(address.resolve("solo", refs, "n").instance, "c1")
        self.assertEqual(address.resolve("shared:2.1", refs, "n").instance, "x1")
        self.assertEqual(address.resolve("shared:2.1/helper", refs, "n").instance, "x2")
        self.assertEqual(address.resolve("codex#x9ab", refs, "n").instance, "x9abcdef")
        self.assertEqual(address.resolve("s1@n", refs, "n", aliases={"s1": "solo"}).instance, "c1")
        refs[0].title = "solo-3a"
        self.assertEqual(address.resolve("solo-3a", refs, "n").instance, "c1")
        # Two tmux servers, both with session "0"; Codex ids started in the same minute share
        # their first 8 characters; one of them also matches an agent outside tmux.
        crowd = address.assign([
            ref("claude", "aaaa1111", "0", "0.0"),
            ref("codex", "01a0fd3a-0001", "0", "0.0"), ref("codex", "01a0fd3a-0002-aaaa", "0", "0.1"),
            ref("codex", "01a0fd3a-0003", "0", "0.1"),
            ref("codex", "01a0fd3a-0004", ""),
            ref("codex", "01a0fd3a-0099", "0", "0.1", sub="helper", parent="01a0fd3a-0002-aaaa"),
            ref("pi", "01a0fd3a-0005", "0", "0.2"), ref("pi", "01a0fd3a-0006", ""),
        ])
        self.assertEqual(len({r.address for r in crowd}), len(crowd))
        for r in crowd:   # every address shown leads back to its agent
            self.assertIs(address.resolve(r.address, crowd, "n"), r, r.address)
        self.assertEqual(address.resolve("codex#01a0fd3a-0002/helper", crowd, "n").instance, "01a0fd3a-0099")
        # A session agent alone keeps its session name, though its id starts like the other's.
        pair = address.assign([ref("codex", "01a0fd3a-0004", ""), ref("codex", "01a0fd3a-0005", "work", "0.0")])
        self.assertEqual([r.address for r in pair], ["codex#01a0fd3a", "work"])
        for r in pair:
            self.assertIs(address.resolve(r.address, pair, "n"), r, r.address)
        for text, code, word in (("shared", USAGE, "ambiguous"), ("nope", USAGE, "no agent"), ("solo@other", NO_INBOX, "not this machine")):
            with self.assertRaises(LinkError) as c:
                address.resolve(text, refs, "n")
            self.assertEqual((c.exception.code, word in str(c.exception)), (code, True), text)


class Envelopes(unittest.TestCase):
    def test_round_trip_and_reply_chain(self):
        e = envelope.make("a@n", "claude", "b@n", "hello\nworld", hop_limit=3)
        text = "noise before\n" + envelope.render(e)
        got = envelope.parse(text)
        self.assertEqual((got.sender, got.sender_kind, got.to, got.message_id, got.conversation, got.hops, got.body, got.can_reply),
                         ("a@n", "claude", "b@n", e.message_id, e.conversation, 1, "hello\nworld", True))
        self.assertIn(f"--conversation {e.conversation} --hops 1", text)
        reply = envelope.make("b@n", "codex", "a@n", "ok", conversation=got.conversation, hops=got.hops, hop_limit=3)
        self.assertEqual((reply.conversation, reply.hops), (e.conversation, 2))

    def test_hop_limit_and_no_reply(self):
        with self.assertRaises(LinkError) as c:
            envelope.make("a@n", "claude", "b@n", "x", conversation="c-1", hops=3, hop_limit=3)
        self.assertEqual(c.exception.code, REFUSED)
        e = envelope.make("h@n", "human", "b@n", "x", can_reply=False)
        self.assertFalse(envelope.parse(envelope.render(e)).can_reply)
        self.assertIsNone(envelope.parse("no header here"))

    def test_hops_accepted_values_survive_the_round_trip(self):
        for given, want in [(0, 1), (9, 10)]:
            e = envelope.make("a@n", "claude", "b@n", "x", conversation="c-1", hops=given, hop_limit=10)
            self.assertEqual(envelope.parse(envelope.render(e)).hops, want, given)
        for bad in (-2, -1, 1.5, "3", True):
            with self.subTest(bad=bad), self.assertRaises(LinkError) as c:
                envelope.make("a@n", "claude", "b@n", "x", hops=bad)
            self.assertEqual(c.exception.code, USAGE)
        with self.assertRaises(LinkError) as c:
            envelope.make("a@n", "claude", "b@n", "x", hops=10, hop_limit=10)
        self.assertEqual(c.exception.code, REFUSED)

    def test_body_round_trips_and_shows_one_header(self):
        """Any body comes back unchanged, and no body line can pass for a second header."""
        head = "[agent-link] from p@n (claude) to b@n"
        parts = ["", "x", "---", "--- end ---", "--- end m-00000000 ---", head,
                 "id m-00000000  conversation c-00000000  hops 1", " " + head, "\t" + head, ">" + head,
                 "> " + head, ">>" + head, ">", "> quoted", "\u00a0" + head, "\u2003" + head, "\x0c" + head]
        breaks = ["\n", "\r", "\r\n", "\x0b", "\x1c", "\x85", "\u2028"]
        rng = random.Random(7)
        bodies = parts + ["".join(rng.choice(parts) + rng.choice(breaks) for _ in range(rng.randint(1, 8)))[:-1]
                          for _ in range(600)] + ["x\n", "x\r", "\n", head + "\r"]
        for body in bodies:
            e = envelope.make("a@n", "codex", "b@n", body)
            text = envelope.render(e)
            lines = text.splitlines()
            heads = [i for i in range(len(lines) - 1)
                     if envelope.HEAD_RE.match(lines[i].strip()) and envelope.META_RE.match(lines[i + 1].strip())]
            self.assertEqual((envelope.parse(text).body, heads), (body, [0]), repr(body))

    def test_body_ends_at_its_end_line(self):
        e = envelope.make("a@n", "claude", "b@n", "hello")
        self.assertEqual(envelope.parse(envelope.render(e) + "\nwhat the recipient wrote next").body, "hello")
        old = envelope.render(e).rsplit("\n", 1)[0]   # an envelope from before the end line
        self.assertEqual(envelope.parse(old + "\nmore").body, "hello\nmore")
        quoted = envelope.render(envelope.make("a@n", "claude", "b@n", "q")).rsplit("\n", 2)[0] + "\n>[agent-link] x"
        self.assertEqual(envelope.parse(quoted).body, ">[agent-link] x")   # not escaped, so not unescaped

    def test_waiting_sender_asks_for_a_plain_answer(self):
        e = envelope.make("a@n", "claude", "b@n", "q", waiting=True)
        text = envelope.render(e)
        self.assertIn("\nreply: WAITING", text)
        self.assertTrue(envelope.parse(text).waiting)
        self.assertFalse(envelope.parse(envelope.render(envelope.make("a@n", "claude", "b@n", "q"))).waiting)


class Claims(Adapter):
    """An adapter that claims every process for one agent, as an inherited variable would."""

    def __init__(self, kind, pid=None):
        self.kind, self.pid = kind, pid

    def whoami(self, ctx, pid, env):
        return AgentRef(kind=self.kind, node="n", instance=f"{self.kind}-1",
                        private={"pid": self.pid} if self.pid else {})


class FirstRun(unittest.TestCase):
    def test_absent_program_is_not_a_failure(self):
        checks, ok = rpc.doctor_checks([("", True, "config"), ("claude", None, "not found here")])
        self.assertEqual(([c["state"] for c in checks], [c["ok"] for c in checks], ok), (["ok", "absent"], [True, True], True))
        checks, ok = rpc.doctor_checks([("claude", None, "not found here"), ("codex", False, "codex on PATH")])
        self.assertEqual(([c["state"] for c in checks], checks[1]["text"], ok), (["absent", "fail"], "codex: codex on PATH", False))

    def test_empty_list_and_skipped_checks_are_spelled_out(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.show("list", {"ok": True, "me": "x", "panes": 1, "kinds": ["claude", "codex"], "agents": []})
            cli.show("doctor", {"ok": True, "checks": [{"ok": True, "state": "absent", "text": "claude: not found here"}]})
        self.assertEqual(out.getvalue().splitlines(),
                         ["0 agents (1 multiplexer pane seen, none runs a supported program: claude, codex)",
                          "skip claude: not found here"])


class RpcDoctorAndList(unittest.TestCase):
    class Reports(Adapter):
        def __init__(self, kind, checks):
            self.kind, self.checks = kind, checks

        def doctor(self, ctx):
            return self.checks

    def run_op(self, op, adapters, panes, tmux="/usr/bin/tmux"):
        cfg = {"node": "n", "hop_limit": 10, "aliases": {}, "nodes": {}, "path": "/nonexistent/config.toml"}
        ctx = Context("n", ProcessTable([("1", "0", "init")]), panes)
        with mock.patch.object(rpc.config, "load", return_value=cfg), mock.patch.object(rpc, "context", return_value=ctx), \
                mock.patch.object(rpc, "adapters", return_value=adapters), mock.patch.object(rpc.shutil, "which", return_value=tmux):
            return rpc.handle({"op": op})

    def test_doctor_exit_code_follows_failures_not_absences(self):
        pane = [Pane("tmux", "s", "1.1", "%1", "1", "/w")]
        absent = [self.Reports("claude", [(None, "not found here")])]
        cases = [
            ("only absences", absent, pane, "/usr/bin/tmux", (True, 0)),
            ("a present program fails", absent + [self.Reports("codex", [(False, "codex on PATH")])], pane, "/usr/bin/tmux", (False, 3)),
            ("no panes yet", absent, [], "/usr/bin/tmux", (True, 0)),
            ("tmux missing", absent, [], None, (False, 3)),
        ]
        for name, adapters, panes, tmux, want in cases:
            with self.subTest(name):
                r = self.run_op("doctor", adapters, panes, tmux)
                self.assertEqual((r["ok"], r["code"]), want)

    def test_list_reports_panes_and_kinds(self):
        r = self.run_op("list", [self.Reports("claude", []), self.Reports("pi", [])], [Pane("tmux", "s", "1.1", "%1", "1", "/w")])
        self.assertEqual((r["agents"], r["panes"], r["kinds"]), ([], 1, ["claude", "pi"]))


class TimeoutText(unittest.TestCase):
    def test_pending_is_not_reported_as_delivered(self):
        class Stuck(Adapter):
            def __init__(self, status):
                self.status = status

            def poll(self, ctx, ref, message_id):
                return TIMEOUT, self.status, ""

        for status, word in [("pending", "not observed"), ("running", "(status running)")]:
            with self.subTest(status):
                code, text = Stuck(status).await_reply(None, None, "m-abc", 0)
                self.assertEqual((code, word in text, "delivered" in text), (TIMEOUT, True, False))


class WhoAmI(unittest.TestCase):
    # codex 201 -> claude 202 -> pi 203 -> bash 204 -> agent-link 205
    table = ProcessTable([("1", "0", "init"), ("201", "1", "codex"), ("202", "201", "claude"),
                          ("203", "202", "pi"), ("204", "203", "bash"), ("205", "204", "agent-link")])

    def who(self, pid, *adapters):
        return rpc.whoami(Context("n", self.table, []), list(adapters), [], pid=pid, env={}).kind

    def test_nearest_agent_process_wins(self):
        cases = [
            ("pi started from claude started from codex", "205", ["codex", "claude", "pi"], "pi"),
            ("claude started from codex", "202", ["codex", "claude"], "claude"),
            ("codex alone", "205", ["codex"], "codex"),
        ]
        pids = {"codex": "201", "claude": "202", "pi": "203"}
        for name, pid, kinds, want in cases:
            with self.subTest(name):
                self.assertEqual(self.who(pid, *[Claims(k, pids[k]) for k in kinds]), want)

    def test_unknown_process_loses_and_ties_go_to_codex(self):
        self.assertEqual(self.who("205", Claims("codex"), Claims("pi", "203")), "pi")
        self.assertEqual(self.who("205", Claims("pi"), Claims("codex")), "codex")


if __name__ == "__main__":
    unittest.main()
