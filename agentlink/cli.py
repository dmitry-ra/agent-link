"""agent-link command line. Every command maps to one rpc request; --json prints the response."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, rpc
from .model import PROTOCOL

GUIDE = Path(__file__).resolve().parent.parent / "AGENTS.md"

USAGE_TEXT = """agent-link - find, read and message AI agents running on this machine

  agent-link whoami                     your own address, as other agents see you
  agent-link list [--all]               every agent: address, kind, state
  agent-link read ADDR [-n N]           what that agent has been doing
  agent-link send ADDR TEXT|-           deliver a message (TEXT '-' reads stdin)
  agent-link ask ADDR TEXT|- [--timeout S]   send and wait for the answer to it
  agent-link status ADDR MESSAGE_ID     has that message been picked up, answered, blocked?
  agent-link guide                      print the full instructions (AGENTS.md)
  agent-link doctor                     check that every supported harness looks as expected
  agent-link rpc                        one JSON request on stdin, JSON response on stdout

  --json        machine-readable output (any command)
  --conversation ID --hops N            used when replying; copy them from the message header

Exit codes: 0 ok, 2 usage/address, 3 no inbox, 4 awaiting approval, 5 timeout,
6 turn failed, 7 paused, 8 refused. Read AGENTS.md for details.
"""


def build_parser():
    ap = argparse.ArgumentParser(prog="agent-link", description=USAGE_TEXT, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"agent-link {__version__} (protocol {PROTOCOL})")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami", parents=[common])
    p = sub.add_parser("list", parents=[common]); p.add_argument("--all", action="store_true")
    p = sub.add_parser("read", parents=[common]); p.add_argument("address"); p.add_argument("-n", type=int, default=30)
    for name in ("send", "ask"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("address"); p.add_argument("text")
        p.add_argument("--conversation"); p.add_argument("--hops", type=int, default=0)
        if name == "ask":
            p.add_argument("--timeout", type=int, default=600)
    p = sub.add_parser("status", parents=[common]); p.add_argument("address"); p.add_argument("message")
    sub.add_parser("doctor", parents=[common])
    sub.add_parser("guide")
    sub.add_parser("rpc")
    return ap


def request_of(a):
    if a.cmd in ("whoami", "doctor"):
        return {"op": a.cmd}
    if a.cmd == "list":
        return {"op": "list", "all": a.all}
    if a.cmd == "read":
        return {"op": "read", "to": a.address, "limit": a.n}
    if a.cmd == "status":
        return {"op": "status", "to": a.address, "message": a.message}
    text = sys.stdin.read() if a.text == "-" else a.text
    req = {"op": a.cmd, "to": a.address, "text": text.rstrip("\n"), "hops": a.hops}
    if a.conversation:
        req["conversation"] = a.conversation
    if a.cmd == "ask":
        req["timeout"] = a.timeout
    return req


def show(cmd, r):
    if not r.get("ok") and "error" in r:
        print(f"agent-link: {r['error']}", file=sys.stderr)
        return
    if cmd == "whoami":
        me = r["me"]
        extra = "" if me["can_receive"] else f"  ({me['note']})"
        print(f"{r['address']}  {me['kind']}  {me['state']}{extra}")
    elif cmd == "list":
        for g in r["agents"]:
            mark = " (you)" if g["address"] == r["me"] else ""
            note = f"  [{g['note']}]" if g["note"] else ""
            print(f"{g['address'] + mark:28} {g['kind']:7} {g['state']:17} {(g['title'] or '-')[:40]}{note}")
    elif cmd == "read":
        g = r["agent"]
        print(f"# {g['address']}  {g['kind']}  {g['state']}  {g['title']}")
        for e in r["entries"]:
            text = e["text"] if len(e["text"]) <= 2000 else e["text"][:2000] + " ..."
            print(f"[{e['time']}] {e['role']}: {text}")
    elif cmd in ("send", "ask"):
        rc = r["receipt"]
        line = f"{rc['status']}: {rc['to']} (instance {rc['instance'][:13]}) message {rc['message_id']}"
        print(line if r["code"] == 0 or cmd == "send" else line, file=sys.stderr if cmd == "ask" else sys.stdout)
        if rc["text"] and rc["text"] not in ("queued", "delivered", ""):
            print(f"  {rc['text']}", file=sys.stderr)
        if cmd == "ask":
            if r["code"] == 0:
                print(r.get("answer", ""))
            elif "answer" in r:
                print(f"agent-link: {r['answer']}", file=sys.stderr)
    elif cmd == "status":
        print(f"{r['message']} at {r['agent']['address']}: {r['message_status']}" + (f"\n{r['detail']}" if r["detail"] else ""))
    elif cmd == "doctor":
        for c in r["checks"]:
            print(("ok   " if c["ok"] else "FAIL ") + c["text"])


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.cmd == "guide":
        print(GUIDE.read_text(encoding="utf-8"), end="")
        return 0
    if a.cmd == "rpc":
        try:
            req = json.loads(sys.stdin.read())
        except ValueError as e:
            print(json.dumps({"protocol": PROTOCOL, "ok": False, "code": 2, "status": "usage", "error": f"bad JSON: {e}"}))
            return 2
        r = rpc.handle(req)
        print(json.dumps(r, ensure_ascii=False))
        return r.get("code", 0)
    r = rpc.handle(request_of(a))
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        show(a.cmd, r)
    return r.get("code", 0)
