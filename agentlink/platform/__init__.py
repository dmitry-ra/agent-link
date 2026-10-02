"""Process table and environment access. The only place that knows how the OS exposes them."""

import sys

__all__ = ["ProcessTable", "environ", "is_alive"]

if sys.platform.startswith("linux"):
    from .linux import ProcessTable, environ, is_alive
else:
    raise ImportError(f"agent-link: platform {sys.platform!r} is not supported yet (see docs/adding-an-adapter.md)")
