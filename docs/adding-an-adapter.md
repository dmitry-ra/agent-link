# Adding an adapter

An adapter teaches agent-link one agent program. The core (addresses, envelope, CLI, rpc) does
not change. Steps:

1. **Investigate the program** and write down the answers, with the version you checked:
   - How is a running instance recognised? (a registry file, a process name, an API)
   - What is its instance id, and what stays stable when it restarts?
   - Where does it take messages, and does a message start a turn?
   - Where is its conversation written, and how is the end of a turn recognised?
   - How does a command running inside it know which instance it is? (`whoami`)
   - Which of these formats are undocumented?
2. **Copy `agentlink/adapters/_template.py`** to `agentlink/adapters/<kind>.py`. Set `kind` and
   the capability flags honestly: an adapter that cannot deliver sets `can_receive = False`.
3. **Implement** `instances`, `whoami`, and whatever the flags promise: `read`, `send`,
   `await_reply`. Return codes from `agentlink/model.py`. Put adapter-only data in
   `AgentRef.private`, never in printed fields.
4. **`doctor`**: when the program is not on this machine at all (`program_present()` is false and its data
   directory is missing), return a single `(None, text)` check: it is shown as `skip`, not as a failure.
   Otherwise, one check per undocumented format you rely on, worded so a failure says what
   changed.
5. **Register** the class in `registry()` in `agentlink/adapters/__init__.py`.
6. **Fixtures and tests**: synthetic files shaped like the real ones in `tests/fixtures/<kind>/`
   (no real conversations, paths or ids), a `tests/test_<kind>.py`, and an entry in
   `tests/conformance.py`.
7. **Document** it in `docs/adapters/<kind>.md` and add a line to "Notes per agent program" in
   `AGENTS.md`.
8. **Live check** with the program running: `list`, `whoami` from inside it, `read`, `send`,
   `ask`, and an answer back with `agent-link send`.

Remote programs (reachable over a network API) fit the same interface; their instances carry a
node name, and the transport layer (docs/protocol.md, Remote nodes) carries the calls.
