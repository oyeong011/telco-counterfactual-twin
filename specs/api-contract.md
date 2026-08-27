# API Contract Boundary

## Status

Reserved and accepted as the future public surface. Todo 1 contains no API implementation.

## HTTP surface

The FastAPI service will expose health, readiness, build identity, approval-root discovery, synthetic demo sessions, scenarios, diagnosis, typed patches, simulations, comparisons, approval requests, benchmarks, event streaming, and downloadable evidence. Mutating demo routes require an opaque demo token plus idempotency key, except the tightly bounded synthetic-only session bootstrap.

The public path set is fixed by the implementation plan, including `GET /healthz`, `GET /readyz`, `GET /build-info`, `GET /.well-known/approval-root`, scenario/patch/simulation/comparison/approval routes under `/api`, `GET /api/runs/{id}/events` for SSE, and evidence/benchmark routes.

## Forbidden surface

No endpoint, tool, event, schema, or hidden adapter may contain execute, apply-to-network, push-config, revoke, shell, arbitrary URL fetch, or generic command authority. `approve` produces a signed evidence decision only.

## Errors and streaming

Boundary failures use stable machine codes with trace/evidence IDs and no credential values. Liveness is process health; readiness includes required safe dependencies. SSE uses ordered event IDs, bounded replay, heartbeat, and reconnect semantics described by ADR 0003.

## MCP boundary

The non-executing MCP server negotiates exactly protocol `2025-06-18`, uses strict Origin/session/version handling, and exposes only typed evidence-state tools. MCP effects are append-only scenario, run, patch, and approval-request evidence; they do not mutate a network or simulator baseline.

## Contract generation

Todo 2 introduces canonical JSON Schemas. Later API and MCP todos generate OpenAPI and MCP tool artifacts from those typed sources. Unknown fields are rejected except beneath an explicitly versioned `extensions` object.
