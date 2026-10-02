# Contributing

- Read [AGENTS.md](AGENTS.md) and [docs/protocol.md](docs/protocol.md) first.
- Standard library only; Python 3.11+. The repository is English and ASCII only (a test enforces
  it). Never put real conversations, paths, host names or ids from your machine in examples or
  fixtures: use neutral ones like `project-1`, `codex-1`, `box`.
- Tests: `python3 -m unittest discover -s tests -t .`. A new test counts only when it fails on
  broken code: add a mutant for the mechanism it guards to `tools/mutate.py` and check
  `python3 tools/mutate.py` kills it.
- Supporting another agent program: follow [docs/adding-an-adapter.md](docs/adding-an-adapter.md).
  Write down the program version you checked, add a `doctor()` check for every undocumented
  format you rely on, and build fixtures from a real sample with private content removed.
- Changes to the envelope, addresses or response fields are protocol changes: update
  docs/protocol.md and bump `PROTOCOL` in `agentlink/model.py` when old peers would misread them.
- Note user-visible changes in [CHANGELOG.md](CHANGELOG.md).
