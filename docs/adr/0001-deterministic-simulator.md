# ADR 0001: Build a deterministic custom simulator

## Status

Accepted.

## Decision

Implement a small custom discrete-event simulator with a stable priority tuple, isolated seeded randomness, canonical versioned inputs, append-only events, and content-hashed outputs. Do not use wall clock, global random state, dict-order accidents, or SimPy.

## Consequences

The project can prove exact replay and explain every event, but it must explicitly model only the bounded telecom behaviors required by the six synthetic fault families. It does not claim carrier-grade physical fidelity.
