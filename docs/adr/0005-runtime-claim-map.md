# ADR 0005: Bind public claims to runtime identity

## Status

Accepted.

## Decision

Every generated metric and deployment claim maps to a source commit, release commit, canonical runtime-tree hash, schema/MCP/policy/trust-root hashes, build time, and the service or UI deployment identity defined by the plan. Hash inputs are sorted POSIX `path\0sha256(file-bytes)\n` records over explicit component path sets.

## Consequences

Evidence and deployment receipts cannot certify themselves. Digest-bearing release manifests remain external immutable release assets; services receive the verified deployed digest at runtime. Missing or mismatched identity fails readiness.
