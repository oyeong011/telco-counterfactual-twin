# ADR 0003: Stream progress with Server-Sent Events

## Status

Accepted.

## Decision

Use SSE for ordered, server-to-browser run progress. Events carry stable IDs and types; reconnect uses scoped `Last-Event-ID`, bounded replay, and heartbeat. Commands remain ordinary authenticated HTTP requests.

## Consequences

SSE is sufficient for one-way progress and easier to audit than a bidirectional socket. It does not introduce a command backchannel or mutation authority.
