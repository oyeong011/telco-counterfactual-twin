# ADR 0004: Prove rollback before claiming deployment authority

## Status

Accepted.

## Decision

Cloudflare Pages preflight creates an isolated temporary project, uploads two tiny deployments, calls the documented rollback endpoint to the first, verifies content, and deletes the project. GCP probes use unique temporary resources, snapshot prior persistent WIF/IAM state, and restore or delete every temporary change.

## Consequences

A missing credential, unsupported cost configuration, failed rollback, or incomplete cleanup yields blocked/invalid evidence. Task 1 does not create the live budget guard, push subscription, or application image.
