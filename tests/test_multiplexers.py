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
      */b:1) printf 'demo\\t1.1\\t%%0\\t200\\t/w\\n' ;;
      */outside) printf 'side\\t1.1\\t%%3\\t300\\t/w\\n' ;;
      *) echo "error connecting to $2" >&2; exit 1 ;;
    esac ;;
  "capture-pane -p -t") echo "screen of $6 on $2" ;;
  *) exit 9 ;;
esac
"""


def bind(path):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.close()


class Tmux(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.sockets = root / "real" / f"tmux-{os.getuid()}"
        self.sockets.mkdir(parents=True)
        (root / "link").symlink_to(root / "real")
        # c: left behind by a server that is gone; b:1 has a colon like the pane id separator.
        for name in ("a", "b:1", "c"):
            bind(self.sockets / name)
        (self.sockets / "not-a-socket").write_text("")
        (root / "other").mkdir()
        self.outside = root / "other" / "outside"
        bind(self.outside)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        (bin_dir / "tmux").write_text(FAKE_TMUX)
        (bin_dir / "tmux").chmod(0o755)
        self.env = {"TMUX_TMPDIR": str(root / "link"), "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    def test_every_server_listed_once_with_ids_unique_across_servers(self):
        listed = list(self.sockets.iterdir())
        gone = self.sockets / "gone"   # listed, then removed before it could be examined
        with mock.patch.dict(os.environ, {**self.env, "TMUX": f"{self.outside},1,0"}), \
                mock.patch.object(Path, "iterdir", lambda _: iter([gone] + sorted(listed))):
            got = tmux.panes(Pane)
        a, b, out = str(self.sockets / "a"), str(self.sockets / "b:1"), str(self.outside)
        self.assertEqual([(p.session, p.pane_id, p.pid, p.server) for p in got],
                         [("side", f"{out}:%3", "300", out), ("project-1", f"{a}:%0", "100", a),
                          ("demo", f"{b}:%0", "200", b)])
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(tmux.screen(got[2]).strip(), f"screen of %0 on {b}")

    def test_current_server_through_a_link_is_not_listed_twice(self):
        # TMUX_TMPDIR goes through a link; $TMUX names the socket by either path.
        want = sorted(str(self.sockets / n) for n in ("a", "b:1", "c"))
        via_link = Path(self.env["TMUX_TMPDIR"]) / self.sockets.name / "a"
        for current in (self.sockets / "a", via_link):
            with mock.patch.dict(os.environ, {**self.env, "TMUX": f"{current},1,0"}):
                self.assertEqual(tmux.servers(), want, current)


if __name__ == "__main__":
    unittest.main()
