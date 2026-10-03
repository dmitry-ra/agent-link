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
sys.path.insert(0, str(ROOT))

# (name, file, original text, mutated text)
MUTANTS = [
    ("address: kind#id ignores the id", "agentlink/address.py",
     "(r.parent if a.sub else r.instance).startswith(a.ident)", "True"),
    ("address: ambiguity resolved by guessing", "agentlink/address.py",
     "    if len(cands) == 1:\n        return cands[0]", "    if cands:\n        return cands[0]"),
    ("address: shared session not qualified", "agentlink/address.py",
     'steps = [r.session, f"{r.session}:{r.position}"] if r.session else []',
     'steps = [r.session] if r.session else []'),
    ("address: program session name not accepted", "agentlink/address.py",
     "cands = [r for r in refs if r.title == a.session and not r.sub]", "cands = []"),
    ("envelope: negative hops accepted", "agentlink/envelope.py",
     "not isinstance(hops, int) or hops < 0:", "not isinstance(hops, int):"),
    ("envelope: header-like body lines not escaped", "agentlink/envelope.py",
     '        escape(e.body),', '        e.body,'),
    ("envelope: body does not stop at its end line", "agentlink/envelope.py",
     "        if end in lines[start:]:", "        if False:"),
    ("envelope: end line does not name the message", "agentlink/envelope.py",
     'return f"{SEPARATOR} end {message_id} {SEPARATOR}"', 'return f"{SEPARATOR} end {SEPARATOR}"'),
    ("envelope: header check ignores Unicode whitespace", "agentlink/envelope.py",
     'LEAD = re.compile(r"[\\s>]*")', 'LEAD = re.compile(r"[ \\t>]*")'),
    ("envelope: escaping splits only at newlines", "agentlink/envelope.py",
     'for l in body.splitlines(keepends=True))\n\n\ndef unescape',
     'for l in body.split("\\n"))\n\n\ndef unescape'),
    ("envelope: envelopes without an end line unescaped", "agentlink/envelope.py",
     '            body = "\\n".join(lines[start:])', '            body = unescape("\\n".join(lines[start:]))'),
    ("envelope: escaping not undone exactly", "agentlink/envelope.py",
     'l[1:] if l.startswith(">") and _looks_like_head(l[1:]) else l', 'l.lstrip(">") if _looks_like_head(l) else l'),
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
    ("address: colliding addresses kept", "agentlink/address.py",
     "        if not clash:", "        if True:"),
    ("tmux: link in TMUX_TMPDIR not resolved", "agentlink/multiplexers/tmux.py",
     'Path(os.path.realpath(os.environ.get("TMUX_TMPDIR") or "/tmp"))', 'Path(os.environ.get("TMUX_TMPDIR") or "/tmp")'),
    ("tmux: panes of the current session only", "agentlink/multiplexers/tmux.py",
     '"list-panes", "-a",', '"list-panes",'),
    ("tmux: pane ids keyed by socket name only", "agentlink/multiplexers/tmux.py",
     'f"{server}:{pane_id}"', 'f"{Path(server).name}:{pane_id}"'),
    ("address: no full id when id prefixes collide", "agentlink/address.py",
     'return steps + [f"{r.kind}#{r.instance[:8]}", f"{r.kind}#{r.instance}"]',
     'return steps + [f"{r.kind}#{r.instance[:8]}"]'),
    ("address: shown address not matched exactly", "agentlink/address.py",
     "    if len(exact) == 1:", "    if False:"),
    ("address: kind#id/sub matched on the subagent's own id", "agentlink/address.py",
     "(r.parent if a.sub else r.instance).startswith(a.ident)", "r.instance.startswith(a.ident)"),
    ("tmux: links in socket paths not resolved", "agentlink/multiplexers/tmux.py",
     "found.add(os.path.realpath(current))", "found.add(current)"),
    ("tmux: current server ignored", "agentlink/multiplexers/tmux.py",
     "found.add(os.path.realpath(current))", "pass"),
    ("tmux: one vanished socket ends the scan", "agentlink/multiplexers/tmux.py",
     "        except OSError:   # gone since the listing\n            pass", "        except OSError:   # gone since the listing\n            break"),
    ("tmux: screen target cut at the first colon", "agentlink/multiplexers/tmux.py",
     'pane.pane_id.rsplit(":", 1)[-1]', 'pane.pane_id.split(":", 1)[-1]'),
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
    ("whoami: the first claiming adapter wins", "agentlink/rpc.py",
     "me = min(found, key=", "me = found[0] or min(found, key="),
    ("whoami: an agent with no known process preferred", "agentlink/rpc.py",
     "                 else len(anc))", "                 else -1)"),
    ("codex: subagent has no process", "agentlink/adapters/codex_cli.py",
     ',\n                                     private={"pid": parent.private.get("pid")}))', "))"),
    ("claude: exited recipient waited for", "agentlink/adapters/claude_code.py",
     '            return TURN_FAILED, "failed", f"Claude Code (pid {pid}) exited before the turn ended"',
     '            return TIMEOUT, "running", ""'),
    ("claude: liveness read after the transcript", "agentlink/adapters/claude_code.py",
     '        alive = is_alive(pid) if pid else True   # before reading: an answer written just before exit still counts\n'
     '        status, answer = answer_after(self._lines(ref), message_id)',
     '        status, answer = answer_after(self._lines(ref), message_id)\n'
     '        alive = is_alive(pid) if pid else True'),
    ("claude: recipient without a pid taken for dead", "agentlink/adapters/claude_code.py",
     "alive = is_alive(pid) if pid else True", "alive = is_alive(pid) if pid else False"),
    ("timeout: never-seen message reported like any other", "agentlink/adapters/__init__.py",
     '    if status == "pending":\n        return (f"no answer', '    if False:\n        return (f"no answer'),
    ("claude doctor: unknown status not named", "agentlink/adapters/claude_code.py",
     'else f"is new to agent-link, shown as is; known: {sorted(STATUS)}"', 'else "known"'),
    ("codex doctor: found record not named", "agentlink/adapters/codex_cli.py",
     '+ ("" if seen == "session_meta" else f", found {seen!r}")', '+ ""'),
    ("doctor: an absent program counted as a failure", "agentlink/rpc.py",
     'return checks, not any(c["state"] == "fail" for c in checks)', 'return checks, all(c["state"] == "ok" for c in checks)'),
    ("claude doctor: missing Claude Code reported as a failure", "agentlink/adapters/claude_code.py",
     'return [(None, f"not found here (no claude on PATH, no claude process, no session registry {base})")]',
     'return [(False, f"session registry {base}")]'),
    ("codex doctor: missing Codex reported as a failure", "agentlink/adapters/codex_cli.py",
     "return [(None, f\"not found here (no codex on PATH", "return [(False, f\"not found here (no codex on PATH"),
    ("doctor: exit code ignores failures", "agentlink/rpc.py",
     '"code": OK if ok else NO_INBOX, "checks": checks}', '"code": OK, "checks": checks}'),
    ("doctor: missing tmux reported as absent", "agentlink/rpc.py",
     'return ("", False, "tmux not on PATH', 'return ("", None, "tmux not on PATH'),
    ("doctor: no panes reported as a failure", "agentlink/rpc.py",
     'return ("", None, "no tmux panes', 'return ("", False, "no tmux panes'),
    ("list: pane count not reported", "agentlink/rpc.py", '"panes": len(ctx.panes),', '"panes": 0,'),
    ("doctor: a running program without its directory taken for absent", "agentlink/adapters/__init__.py",
     "or any(title.search(a) for a in ctx.table.args.values())", "or False"),
    ("pi doctor: missing Pi reported as present", "agentlink/adapters/pi.py",
     "if not any(d.exists() for d in dirs) and not program_present(ctx, \"pi\", PI_TITLE):", "if False:"),
    ("list: empty result printed as nothing", "agentlink/cli.py",
     "        if not r[\"agents\"]:\n", "        if False:\n"),
    ("pi: dead registry entries listed", "agentlink/adapters/pi.py",
     'registry_entries(self.dirs()) if runs_pi(ctx, d["pid"])]', "registry_entries(self.dirs())]"),
    ("pi: reused pid taken for Pi", "agentlink/adapters/pi.py",
     'return bool(PI_TITLE.match(ctx.table.args.get(str(pid), "")))', "return str(pid) in ctx.table.args"),
    ("pi: shared registry directory read", "agentlink/adapters/pi.py",
     "        if not private_dir(d):\n            continue\n", ""),
    ("pi: listener of another user trusted", "agentlink/adapters/pi.py",
     "        if uid != os.getuid():", "        if False:"),
    ("pi: any agent-link message taken for the one asked about", "agentlink/adapters/pi.py",
     'seen = is_inbox(d) and tag in text_of(d.get("content"))', "seen = is_inbox(d)"),
    ("pi: any custom entry ends the turn", "agentlink/adapters/pi.py",
     'return (d.get("type") == "custom" and d.get("customType") == CUSTOM_TYPE\n'
     '            and (d.get("data") or {}).get("event") == "settled")', 'return d.get("type") == "custom"'),
    ("pi: failed turn polled as answered", "agentlink/adapters/pi.py",
     'return TURN_FAILED, status, f"turn ended with an error: {text}"', 'return OK, "answered", text'),
    ("pi: message dropped by a session switch waited for", "agentlink/adapters/pi.py",
     '            if status == "pending":\n                return TURN_FAILED',
     '            if False:\n                return TURN_FAILED'),
    ("pi: Pi without the extension not listed", "agentlink/adapters/pi.py",
     "            if pid:\n", "            if False:\n"),
    ("pi: whoami only checks itself", "agentlink/adapters/pi.py",
     "anc = ctx.table.ancestors(pid)", "anc = [str(pid)]"),
    ("pi: whoami takes the farthest Pi", "agentlink/adapters/pi.py",
     "return min(mine, key=lambda t: t[0])[1]", "return max(mine, key=lambda t: t[0])[1]"),
    ("pi: no whoami from the session variable", "agentlink/adapters/pi.py",
     '        if env.get("PI_SESSION_ID"):', "        if False:"),
    ("pi: inbox messages not read", "agentlink/adapters/pi.py",
     '    if is_inbox(d):\n        return "inbox"', '    if False:\n        return "inbox"'),
    ("pi: turn ends at the first stop or error (file only)", "agentlink/adapters/pi.py",
     "if is_settled(d) or (finished and", 'if is_settled(d) or (final or {}).get("stopReason") in ("stop", "error") or (finished and'),
    ("pi: a follow-up in the same run takes the answer", "agentlink/adapters/pi.py",
     ' or (finished and (is_inbox(d) or message(d, "user")))', ""),
    ("pi: steering ends the turn", "agentlink/adapters/pi.py",
     "(finished and (is_inbox(d)", "((is_inbox(d)"),
    ("pi: failed turn reported as answered", "agentlink/adapters/pi.py",
     '            if final.get("stopReason") in FAILED:\n                return "failed"', '            if False:\n                return "failed"'),
    ("pi: refusal reported as delivered", "agentlink/adapters/pi.py",
     'if reply.get("ok") is True:', "if True:"),
    ("pi: oversized message sent", "agentlink/adapters/pi.py",
     "    if len(wire) > MAX_LINE_BYTES:", "    if False:"),
    ("pi: exited Pi waited for", "agentlink/adapters/pi.py",
     "        if not alive:", "        if False:"),
    ("pi: open dialog not reported", "agentlink/adapters/pi.py",
     'if live and live.get("state") == "awaiting-approval":', "if False:"),
    ("pi extension: half a line delivered", "integrations/pi/agent-link.ts",
     "} else if (nl >= 0) {", "} else {"),
    ("pi extension: message delivered during a compaction", "integrations/pi/agent-link.ts",
     "if (!running && !ctx.isIdle()) {", "if (false) {"),
    ("pi extension: busy session steered", "integrations/pi/agent-link.ts",
     'deliverAs: "followUp"', 'deliverAs: "steer"'),
    ("pi extension: no settled marker", "integrations/pi/agent-link.ts",
     '\t\tpi.appendEntry(CUSTOM_TYPE, { event: "settled" });\n', ""),
    ("pi extension: both copies serve when loaded twice", "integrations/pi/agent-link.ts",
     "if (shared[OWNER] !== undefined && !mine()) return;", ""),
    ("pi extension: dialog not published", "integrations/pi/agent-link.ts",
     'prompt = event.title ?? "";', ""),
    ("pi extension: registry left after shutdown", "integrations/pi/agent-link.ts",
     "fs.rmSync(`${base}.json`, { force: true });", ""),
    ("pi extension: shared directory accepted", "integrations/pi/agent-link.ts",
     "(st.mode & 0o077) !== 0", "false"),
    ("pi extension: entry written through a link", "integrations/pi/agent-link.ts",
     '\t\tfs.rmSync(`${base}.json.tmp`, { force: true });\n'
     '\t\tfs.writeFileSync(`${base}.json.tmp`, `${JSON.stringify(entry)}\\n`, { mode: 0o600, flag: "wx" });',
     '\t\tfs.writeFileSync(`${base}.json.tmp`, `${JSON.stringify(entry)}\\n`, { mode: 0o600 });'),
    ("pi extension: rename not published", "integrations/pi/agent-link.ts",
     '\tpi.on("session_info_changed", async () => {\n\t\tif (mine()) publish();', '\tpi.on("session_info_changed", async () => {\n\t\tif (false) publish();'),
    ("pi extension: socket left open to the group", "integrations/pi/agent-link.ts",
     "fs.chmodSync(socket, 0o600);", ""),
]


def run_tests(tree):
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                       cwd=tree, capture_output=True, text=True, timeout=300)
    return p.returncode == 0


def main():
    if not run_tests(ROOT):
        print("baseline: tests already fail; fix them first")
        return 1
    from tests.test_pi import typescript_node
    if not typescript_node():
        print("note: no node on PATH runs TypeScript; the Pi extension tests skip and its mutants survive")
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
