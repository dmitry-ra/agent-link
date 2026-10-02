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

    def test_no_machine_specifics(self):
        # A list of one machine's names would itself leak them; look for the shapes instead.
        home = re.compile(r"/(home|Users)/[a-z_][a-z0-9_-]*/|[A-Z]:\\Users\\")
        ipv4 = re.compile(r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b)(\d{1,3}\.){3}\d{1,3}\b")
        for f in ROOT.rglob("*"):
            if f.is_file() and ".git" not in f.parts and f.suffix in (".py", ".md", ".sh", ".toml", ".yml", ""):
                text = f.read_text(encoding="utf-8", errors="replace")
                self.assertIsNone(home.search(text), f"absolute home path in {f.relative_to(ROOT)}")
                self.assertIsNone(ipv4.search(text), f"IPv4 address in {f.relative_to(ROOT)}")

    def test_repository_is_keyboard_ascii(self):
        # Printable ASCII plus newline and tab: what can be typed on any keyboard. No typographic
        # dashes or quotes, no non-breaking spaces, no control characters, in names or contents.
        for f in ROOT.rglob("*"):
            if ".git" in f.parts or "__pycache__" in f.parts:
                continue
            rel = f.relative_to(ROOT)
            self.assertTrue(all(0x20 <= ord(c) <= 0x7E for c in str(rel)), f"non-keyboard character in name {rel}")
            if f.is_file() and not f.is_symlink() and f.stat().st_size < 10**6:
                for n, line in enumerate(f.read_bytes().split(b"\n"), 1):
                    bad = [b for b in line if not (0x20 <= b <= 0x7E or b == 0x09)]
                    self.assertFalse(bad, f"{rel}:{n}: byte 0x{bad[0]:02x}" if bad else "")


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


if __name__ == "__main__":
    unittest.main()
