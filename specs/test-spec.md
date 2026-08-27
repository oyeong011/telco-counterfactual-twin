# Test Specification: Telco Counterfactual Twin

## Status

Accepted. Behavior is developed red-green-refactor; generated evidence supplements but never replaces observable assertions.

## Todo 1 contract tests

The bootstrap scripts are specified before implementation and exercised through their real CLI surface with the uv-managed Python 3.12 interpreter.

- Spec validation accepts the complete required tree and rejects a missing ADR.
- Preflight reporting redacts environment credentials, records an explicit blocked state, and validates that blocked outcome with exit zero.
- Token-like material, malformed provider JSON, inconsistent ready claims, unsupported cost settings, dirty worktrees, and incomplete cleanup return exit three.
- Workflow waiting selects only a run whose `headSha` equals `bootstrap_sha`; a stale head, malformed response, failed conclusion, or timeout returns exit three.
- WIF planning fixes the pool, provider, issuer, mappings, immutable owner ID, exact repositories, service account, and principal sets.

## Test layers

- Unit tests cover deterministic ordering, parsers, typed constraints, safety, cryptography, hashing, and stable error codes.
- Integration tests exercise real FastAPI/MCP adapters, event streaming, approval flow, and containerized dependencies where introduced.
- End-to-end tests exercise the public browser and API flow; mock-only passage is not acceptance.
- Contract checks snapshot generated JSON Schema, OpenAPI, MCP tool schemas, and build identity.

## Determinism and fault corpus

- The diagnosis corpus contains exactly 72 cases: each of six fault families has six development and six held-out cases.
- Macro-F1 uses only the 36 held-out cases. The development split never enters the score.
- Repeated same-seed runs have one trace hash; a changed seed changes topology while preserving invariants.
- Timestamp ties use stable `(timestamp, priority, sequence_id)` ordering.
- Stale or noisy observations carry quality flags and block approval eligibility.
- Alarm instructions remain untrusted evidence and cannot alter diagnosis or policy control flow.

## Safety corpus

The frozen set contains 20 unsafe and 20 safe patches. Acceptance requires unsafe blocks `20/20` and safe false blocks no greater than `2/20`. Baseline mutation, unbounded patches, stale telemetry, missing simulation, invalid proof chains, nonce replay, expiry, and cross-session evidence are negative cases.

## Manual QA

The CLI manual channel runs report then validate against the recorded bootstrap SHA. A pass requires exit zero, outcome `deployment-blocked` when authority is absent, explicit status/evidence for every provider permission, no token-like content, and an ignored generated artifact. A fabricated leaked-token fixture must exit three.

## Adversarial probes

- Malformed provider JSON and misleading ready output are rejected.
- Stale workflow heads and hung runs are rejected without accepting a different run.
- Dirty worktrees cannot generate an accepted report.
- Interrupted cleanup receipts fail while any temporary resource or binding remains.
- Prompt injection is not an execution channel: workflow logs are parsed only for an exact terminal marker and never sent to a model.
- Cancel/resume is not applicable to the one-shot preflight; a cancelled workflow is a terminal failure and a new invocation begins a fresh wait.
