import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentlink.multiplexers import Pane, tmux

FAKE_TMUX = """#!/bin/sh
[ "$1" = "-S" ] || exit 9
case "$3 $4 $5" in
  "list-panes -a -F")
    case "$2" in
      */a) printf 'project-1\\t1.1\\t%%0\\t100\\t/w\\n' ;;
      */b) printf 'demo\\t1.1\\t%%0\\t200\\t/w\\n' ;;
      *) echo "error connecting to $2" >&2; exit 1 ;;
    esac ;;
  "capture-pane -p -t") echo "screen of $6 on $2" ;;
  *) exit 9 ;;
esac
"""


class Tmux(unittest.TestCase):
    def test_every_server_listed_with_ids_unique_across_servers(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        sockets = root / f"tmux-{os.getuid()}"
        sockets.mkdir()
        for name in ("a", "b", "c"):   # c: a socket left behind by a server that is gone
            s = socket.socket(socket.AF_UNIX)
            s.bind(str(sockets / name))
            s.close()
        (sockets / "not-a-socket").write_text("")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text(FAKE_TMUX)
        (bin_dir / "tmux").chmod(0o755)
        env = {"TMUX_TMPDIR": str(root), "TMUX": "", "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        with mock.patch.dict(os.environ, env):
            got = tmux.panes(Pane)
        a, b = str(sockets / "a"), str(sockets / "b")
        self.assertEqual([(p.session, p.pane_id, p.pid, p.server) for p in got],
                         [("project-1", f"{a}:%0", "100", a), ("demo", f"{b}:%0", "200", b)])
        with mock.patch.dict(os.environ, env):
            self.assertEqual(tmux.screen(got[1]).strip(), f"screen of %0 on {b}")


if __name__ == "__main__":
    unittest.main()
