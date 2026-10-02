import unittest

from agentlink import address, envelope
from agentlink.model import NO_INBOX, REFUSED, USAGE, AgentRef, LinkError


def ref(kind, instance, session="", position="", sub="", parent=""):
    return AgentRef(kind=kind, node="n", instance=instance, session=session, position=position, sub=sub, parent=parent)


class Addresses(unittest.TestCase):
    def test_parse_every_documented_form(self):
        cases = {
            "homelab-1": ("homelab-1", "", "", "", "", ""),
            "homelab-1:2.1": ("homelab-1", "2.1", "", "", "", ""),
            "codex-1/reviewer": ("codex-1", "", "", "", "reviewer", ""),
            "codex#01a0fd03": ("", "", "codex", "01a0fd03", "", ""),
            "codex#01a0fd03/helper@vm": ("", "", "codex", "01a0fd03", "helper", "vm"),
            "homelab-1@hel": ("homelab-1", "", "", "", "", "hel"),
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


if __name__ == "__main__":
    unittest.main()
