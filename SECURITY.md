# Security

## Scope

agent-link connects agents that run under one user account on one machine. Its trust boundary
is that account: it does not authenticate one local process to another, because any process of
the same user can already reach the same files and sockets. What it adds is labelling (every
message says it comes from another agent, with a sender address computed by agent-link) and
loop limits.

In scope:
- a message reaching an agent of a different user;
- agent-link reading or exposing secrets (for example Claude Code `*.key` files or credentials);
- the sender address being forgeable through agent-link itself;
- a way to bypass the hop limit through agent-link.

Out of scope:
- a process of the same user writing to an agent inbox without agent-link;
- an agent acting on a peer's message against its user's interest (that is the agent's rules
  and the user's configuration; see "Security model" in README.md).

## Reporting

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security
advisories) on this repository rather than in a public issue.
