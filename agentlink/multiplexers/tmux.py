"""tmux provider."""

import shutil
import subprocess

NAME = "tmux"
FORMAT = "#{session_name}\t#{window_index}.#{pane_index}\t#{pane_id}\t#{pane_pid}\t#{pane_current_path}"


def panes(make):
    if not shutil.which("tmux"):
        return []
    try:
        out = subprocess.run(["tmux", "list-panes", "-a", "-F", FORMAT], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    result = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 5:
            result.append(make(NAME, *parts))
    return result


def screen(pane):
    try:
        out = subprocess.run(["tmux", "capture-pane", "-p", "-t", pane.pane_id], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout
