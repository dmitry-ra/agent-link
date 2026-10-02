#!/usr/bin/env python3
"""Break each core mechanism in turn and require the test suite to fail.

A test that stays green when the code it guards is broken guards nothing. Run from the
repository root: python3 tools/mutate.py. Exit code 1 if any mutant survives.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (name, file, original text, mutated text)
MUTANTS = [
    ("address: kind#id ignores the id", "agentlink/address.py",
     "r.instance.startswith(a.ident)", "True"),
    ("address: ambiguity resolved by guessing", "agentlink/address.py",
     "    if len(cands) == 1:\n        return cands[0]", "    if cands:\n        return cands[0]"),
    ("address: shared session not qualified", "agentlink/address.py",
     "shared = len(per_session[r.session]) > 1", "shared = False"),
    ("address: program session name not accepted", "agentlink/address.py",
     "cands = [r for r in refs if r.title == a.session and not r.sub]", "cands = []"),
    ("envelope: hop limit not enforced", "agentlink/envelope.py",
     "    if hops > hop_limit:", "    if False:"),
    ("envelope: waiting sender not announced", "agentlink/envelope.py",
     "    if e.waiting:", "    if False:"),
    ("envelope: conversation not carried", "agentlink/envelope.py",
     "conversation or new_id(\"c\")", "new_id(\"c\")"),
    ("claude: dead sessions listed", "agentlink/adapters/claude_code.py",
     "registry_entries(base) if ctx.table.alive(d[\"pid\"])]", "registry_entries(base)]"),
    ("claude: whoami only checks itself", "agentlink/adapters/claude_code.py",
     "for anc in ctx.table.ancestors(pid):", "for anc in [str(pid)]:"),
    ("claude: pane taken from the registry pane id", "agentlink/adapters/claude_code.py",
     'pane = multiplexers.pane_of(d["pid"], ctx.panes, ctx.table)',
     'pane = ctx.pane_by_id.get(split_tmux(d.get("tmux", ""))[1])'),
    ("tmux: only one server listed", "agentlink/multiplexers/tmux.py",
     "    for server in servers():", "    for server in servers()[:1]:"),
    ("claude: answer taken before end_turn", "agentlink/adapters/claude_code.py",
     "        if m.get(\"stop_reason\") == \"end_turn\":", "        if True:"),
    ("claude: answer split across records cut short", "agentlink/adapters/claude_code.py",
     'if end_id is not None and not (d.get("type") == "assistant" and m.get("id") == end_id):', "if end_id is not None:"),
    ("codex: /new ignored when no turn typed yet", "agentlink/adapters/codex_cli.py",
     'if kind in ("session_start", "new_session"):', 'if kind == "session_start":'),
    ("codex: no binding by marker time", "agentlink/adapters/codex_cli.py",
     "if when is not None and abs(when - marker) <= 3:", "if False:"),
    ("codex: resume not recognised", "agentlink/adapters/codex_cli.py",
     'elif t == "event_msg" and p.get("type") == "thread_settings_applied":', 'elif False:'),
    ("codex: ambiguous marker match bound anyway", "agentlink/adapters/codex_cli.py",
     "return found.pop() if len(found) == 1 else None", "return found.pop() if found else None"),
    ("codex: turn errors swallowed", "agentlink/adapters/codex_cli.py",
     "return (\"error\", answers + [err]) if err else", "return"),
    ("codex: subagent shows parent history", "agentlink/adapters/codex_cli.py",
     "            return recs[i:]", "            return recs"),
    ("codex: injected blocks shown", "agentlink/adapters/codex_cli.py",
     "    return role == \"developer\" or", "    return False and role == \"developer\" or"),
    ("codex: pause not reported on send", "agentlink/adapters/codex_cli.py",
     "        if ref.state == \"paused\":", "        if False:"),
    ("codex: approval dialog not seen", "agentlink/adapters/codex_cli.py",
     "dialog = any(\"Would you like to run\" in l", "dialog = any(False and \"Would you like to run\" in l"),
]


def run_tests(tree):
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=tree, capture_output=True, text=True, timeout=300)
    return p.returncode == 0


def main():
    if not run_tests(ROOT):
        print("baseline: tests already fail; fix them first")
        return 1
    survivors = 0
    with tempfile.TemporaryDirectory() as tmp:
        for name, rel, old, new in MUTANTS:
            tree = Path(tmp) / "tree"
            if tree.exists():
                shutil.rmtree(tree)
            shutil.copytree(ROOT, tree, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            f = tree / rel
            src = f.read_text()
            if src.count(old) != 1:
                print(f"STALE   {name}: pattern not found exactly once in {rel}")
                survivors += 1
                continue
            f.write_text(src.replace(old, new))
            green = run_tests(tree)
            print(("SURVIVED" if green else "killed  ") + f" {name}")
            survivors += green
    print(f"{len(MUTANTS) - survivors}/{len(MUTANTS)} mutants killed")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
