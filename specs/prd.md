# Product Requirements: Telco Counterfactual Twin

## Status

Accepted for v0.1 implementation. This document defines the product boundary; later todos implement it under the referenced ADRs and test specification.

## Problem

Operations proposals are risky when diagnosis, candidate changes, expected impact, safety constraints, and approval evidence are scattered across tools. The project will provide a deterministic, synthetic twin in which a candidate patch must be simulated against an unchanged baseline before it can become eligible for an evidence-only approval decision.

## Users and value

- An operator demonstrates diagnosis and counterfactual comparison without touching a live network.
- A reviewer inspects provenance, constraints, blast radius, and signed approval evidence.
- A recruiter can run one local scenario and verify that simulation and approval cannot be skipped.

## In scope

- A custom, deterministic discrete-event simulator with stable ordering, fixed seeds, versioned inputs, and content hashes.
- Synthetic cells/gNBs, UE cohorts, backhaul, AMF/SMF/UPF, slices, config history, alarms, and telemetry.
- Exactly six fault families: radio congestion, backhaul degradation, UPF saturation, neighbor/handover misconfiguration, slice scheduler misallocation, and alarm prompt injection.
- Typed remediation patches, baseline/candidate comparison, blast-radius and constraint checks, and a local safety-policy gate.
- Signed, short-lived approval evidence that cannot execute a patch.
- A FastAPI service, React/TypeScript operations console, and non-executing MCP tools with append-only evidence effects.
- CPU-only, scale-to-zero deployment: Cloud Run API and Cloudflare Pages UI.

## Out of scope

- Real SKT/operator/customer data, credentials, MSISDNs, proprietary topology, or carrier-production claims.
- Real or simulated mutation authority, configuration pushes, command execution, or revoke/execute endpoints.
- Foundation-model training, persistent GPUs, Kafka, Kubernetes, Neo4j, vector databases, or decorative microservices.
- A generic chatbot or any path in which alarm prose overrides typed observations.

## Product invariants

1. Identical versioned inputs and seed produce byte-stable trace hashes across isolated processes.
2. Baseline state remains unchanged by candidate simulation.
3. Unknown, unsafe, stale, unsimulated, unsigned, expired, replayed, or cross-session evidence cannot approve.
4. Approval records eligibility and provenance only; no component has an execution capability.
5. Every metric or public claim links to a fresh artifact carrying command, commit, seed, and contract hashes.
6. Provider credentials and raw access tokens never enter logs, artifacts, or repository history.

## Acceptance outcomes

- The 36 held-out diagnosis cases reach six-class macro-F1 at least 0.85 without development cases entering the score.
- All 20 unsafe patches are blocked and no more than 2 of 20 safe patches are falsely blocked.
- Contract, simulator safety, approval, MCP, evidence hashing, and replay paths meet their specified coverage gates.
- A public end-to-end demo proves scenario creation through simulation, comparison, and evidence-only approval.

## Delivery-authority gate

Application implementation may proceed after Todo 1 even when cloud authority is truthfully blocked. Public-deployment completion may not. The redacted preflight requires a public non-fork GitHub repository on `main`, an exact-head WIF workflow, GCP project and billing authority, Cloudflare account/Pages authority, Neon read authority, and clean temporary-resource cleanup. Missing authority yields `deployment-blocked`; invalid or leaked evidence yields exit three.
