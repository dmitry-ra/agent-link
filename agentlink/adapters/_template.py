"""Template for a new adapter. Copy to <kind>.py and fill in every TODO.

Checklist (docs/adding-an-adapter.md has the details):
  1. How is a running agent of this kind recognised? (session registry, process name, API)
  2. What stays stable across its restarts, and what is its instance id?
  3. Where does it take messages, and how does a message wake it up?
  4. Where is its conversation written, and how is the end of a turn recognised?
  5. How does a process running inside it (a shell command it executes) know who it is?
  6. Which on-disk formats are undocumented? Each one gets a doctor() check.
"""

from . import Adapter


class Template(Adapter):
    kind = "template"            # TODO: short lowercase name used in addresses (kind#id)
    can_receive = False
    can_read = False
    reply_detection = False
    subagents = False

    def instances(self, ctx):
        return []                # TODO

    def whoami(self, ctx, pid, env):
        return None              # TODO
