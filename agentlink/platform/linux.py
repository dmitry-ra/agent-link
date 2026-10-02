"""Linux: process table from ps, environment from /proc/<pid>/environ."""

import os
import subprocess


class ProcessTable:
    """Snapshot of every process: pid -> (ppid, argv string)."""

    def __init__(self, rows=None):
        if rows is None:
            out = subprocess.run(["ps", "-e", "-o", "pid=,ppid=,args="], capture_output=True, text=True, timeout=10).stdout
            rows = []
            for line in out.splitlines():
                parts = line.split(None, 2)
                if len(parts) >= 2:
                    rows.append((parts[0], parts[1], parts[2] if len(parts) == 3 else ""))
        self.parent = {pid: ppid for pid, ppid, _ in rows}
        self.args = {pid: args for pid, _, args in rows}
        self.children = {}
        for pid, ppid, _ in rows:
            self.children.setdefault(ppid, []).append(pid)

    def alive(self, pid):
        return str(pid) in self.args

    def ancestors(self, pid):
        """pid itself first, then its parent, up to init."""
        out, cur = [], str(pid)
        while cur and cur not in out and cur != "0":
            out.append(cur)
            cur = self.parent.get(cur)
        return out

    def descendants(self, pid):
        out, stack = [], [str(pid)]
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack += self.children.get(cur, [])
        return out


def environ(pid):
    """Environment of a process owned by this user; {} when unreadable."""
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read()
    except OSError:
        return {}
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode(errors="replace")] = v.decode(errors="replace")
    return env


def is_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False
