# Telco Counterfactual Twin Design

## Status

Accepted implementation design for the public v0.1 portfolio project.

## Architecture

The system has one deterministic Python simulation/evaluation core, one FastAPI boundary, one non-executing MCP boundary, and one React/TypeScript console. Components share versioned schemas and evidence hashes, not mutable hidden state. A bounded in-memory demo store is explicit and non-durable.

```text
synthetic scenario -> typed observations -> diagnosis -> typed patch
        |                                      |
        +---- immutable baseline --------------+
                                               v
candidate simulation -> comparison -> local safety gate
                                               |
                                               v
                           evidence-only approval request/proof
```

No arrow leaves the system toward a network control plane.

## Deterministic core

Inputs bind schema version, topology/config versions, fixed seed, and content hashes. Events use stable `(timestamp, priority, sequence_id)` ordering and an isolated RNG. Baseline and candidate runs share the same initial manifest while remaining independently immutable. Canonical serialization produces replay hashes.

## Safety and approval

Typed patches have bounded targets and parameters. Constraints evaluate observation freshness, blast radius, slice SLOs, and policy rules before approval eligibility. A root-certified Ed25519 session key signs a 60-second proof bound to patch, simulation, policy, session, request, and nonce. Approval records evidence only.

## Delivery architecture

The future API runs CPU-only on a single scale-to-zero Cloud Run service; the static UI deploys to Cloudflare Pages. Neon is reserved for the later Evidence Plane, so the Twin Todo 1 probe is read-only there. GitHub Actions uses exact-repository WIF with no stored GCP service-account key.

## Delivery phases

1. Lock specifications and truthfully preflight deployment authority.
2. Generate domain and evidence schemas.
3. Implement deterministic simulation, faults, counterfactuals, safety, and approval.
4. Add evaluation, API, MCP, UI, container/CI, release identity, and deployment.
5. Integrate the separately versioned MCP Evidence Plane only through published contracts.

## Verification

Every behavior begins with a failing test. Static gates use Python 3.12, Ruff, basedpyright, mypy, pytest, and strict TypeScript. Public claims require generated artifacts bound to commit, command, seed, contract hashes, and runtime identity. Cloud authority is never inferred from installed tools or named environment variables.
