"""AGENTS.md cannot drift from the CLI, and every adapter keeps the promises its flags make."""

import re
import unittest
from pathlib import Path
from unittest import mock

from agentlink import cli
from agentlink.adapters import Adapter, registry
from agentlink.model import NO_INBOX, AgentRef, LinkError
from tests.helpers import context

ROOT = Path(__file__).resolve().parent.parent


class DocsMatchCli(unittest.TestCase):
    def test_every_command_and_flag_in_agents_md_exists(self):
        doc = (ROOT / "AGENTS.md").read_text()
        # Only code: fenced blocks and inline `code`; prose may say "agent-link never guesses".
        text = "\n".join(re.findall(r"```.*?```", doc, re.S) + re.findall(r"`[^`\n]+`", doc))
        parser = cli.build_parser()
        sub = next(a for a in parser._actions if a.dest == "cmd").choices
        commands = set(re.findall(r"(?<![\[\w-])agent-link (\w+)", text)) - {"repository"}
        self.assertTrue(commands, "no commands found in AGENTS.md")
        for c in commands:
            self.assertIn(c, sub, f"AGENTS.md mentions 'agent-link {c}', the CLI has no such command")
        for c, flag in re.findall(r"(?<![\[\w-])agent-link (\w+)[^\n`|]*?(--[a-z-]+)", text):
            known = {o for a in sub[c]._actions for o in a.option_strings}
            self.assertIn(flag, known, f"AGENTS.md uses 'agent-link {c} ... {flag}'")


class Conformance(unittest.TestCase):
    def test_adapters_keep_their_promises(self):
        ctx = context()
        for a in registry():
            with self.subTest(kind=a.kind):
                self.assertIsInstance(a, Adapter)
                self.assertTrue(re.fullmatch(r"[a-z][a-z0-9-]*", a.kind))
                with mock.patch("agentlink.multiplexers.screen", return_value=""):
                    refs = a.instances(ctx)
                self.assertTrue(all(isinstance(r, AgentRef) and r.kind == a.kind for r in refs))
                ref = AgentRef(kind=a.kind, node="n", instance="x", can_receive=False, note="test")
                with self.assertRaises(LinkError) as c:
                    a.send(ctx, ref, "x")
                self.assertEqual(c.exception.code, NO_INBOX)
                for flag in ("can_receive", "can_read", "reply_detection", "subagents"):
                    self.assertIsInstance(getattr(a, flag), bool)
                with mock.patch("agentlink.multiplexers.screen", return_value=""):
                    checks = a.doctor(ctx)
                self.assertTrue(all(ok in (True, False, None) and isinstance(text, str) for ok, text in checks), checks)


if __name__ == "__main__":
    unittest.main()
