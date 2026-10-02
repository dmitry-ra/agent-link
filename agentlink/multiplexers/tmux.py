"""tmux provider."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

NAME = "tmux"
FORMAT = "#{session_name}\t#{window_index}.#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_current_path}"


def servers():
    """Socket paths of every tmux server of this user.

    Like tmux itself, this finds the servers in the socket directory of the caller's
    TMUX_TMPDIR, plus the current one. Agents may live in any of them, and tmux pane ids ("%0")
    are unique only inside one server, so pane ids here carry the socket path.
    """
    found = set()
    # tmux resolves links in these paths; so must we, or one server is listed twice.
    current = os.environ.get("TMUX", "").split(",")[0]
    if current:
        found.add(os.path.realpath(current))
    base = Path(os.path.realpath(os.environ.get("TMUX_TMPDIR") or "/tmp")) / f"tmux-{os.getuid()}"
    try:
        entries = list(base.iterdir())
    except OSError:
        entries = []
    for p in entries:
        try:
            if stat.S_ISSOCK(p.lstat().st_mode):
                found.add(str(p))
        except OSError:   # gone since the listing
            pass
    return sorted(found)


def panes(make):
    if not shutil.which("tmux"):
        return []
    result = []
    for server in servers():
        try:
            out = subprocess.run(["tmux", "-S", server, "list-panes", "-a", "-F", FORMAT],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode != 0:   # a socket left behind by a server that is gone
            continue
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 5:
                session, position, pane_id, pid, cwd = parts
                result.append(make(NAME, session, position, f"{server}:{pane_id}", pid, cwd, server))
    return result


def screen(pane):
    target = pane.pane_id.rsplit(":", 1)[-1]
    try:
        out = subprocess.run(["tmux", "-S", pane.server, "capture-pane", "-p", "-t", target],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout
