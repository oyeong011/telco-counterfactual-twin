# ADR 0002: Exclude all network mutation authority

## Status

Accepted and irreversible for v0.1.

## Decision

No component may execute, push, apply, schedule, or revoke a network change. A typed patch is simulation input. Approval is a signed evidence-eligibility decision, never an execution grant. MCP tools may append evidence state only.

## Consequences

There is no hidden adapter or future-flagged execution endpoint. Demonstrations end at downloadable evidence. Any proposed mutation surface requires a new product, threat model, and approval outside this repository.
