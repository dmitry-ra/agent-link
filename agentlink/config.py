"""User configuration: ~/.config/agent-link/config.toml (override with AGENT_LINK_CONFIG).

Everything specific to one machine lives here, never in the repository:

    node = "box"                  # name of this machine in addresses; default: short hostname
    hop_limit = 10                # messages in one agent conversation before refusal

    [aliases]
    p1 = "project-1"              # short names people use for agent sessions

    [nodes.vm-codex]              # remote nodes (not implemented yet, see docs/protocol.md)
    transport = "ssh"
    target = "vm-codex"
"""

import os
import socket
import tomllib
from pathlib import Path

DEFAULT_HOP_LIMIT = 10


def path():
    env = os.environ.get("AGENT_LINK_CONFIG")
    if env:
        return Path(env)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-link" / "config.toml"


def load():
    p = path()
    data = {}
    if p.exists():
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
    return {
        "node": data.get("node") or socket.gethostname().split(".")[0],
        "hop_limit": int(data.get("hop_limit", DEFAULT_HOP_LIMIT)),
        "aliases": dict(data.get("aliases", {})),
        "nodes": dict(data.get("nodes", {})),
        "path": str(p),
    }
