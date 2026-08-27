# Threat Model: Telco Counterfactual Twin

## Status

Accepted for the v0.1 design boundary.

## Assets

- Deterministic scenario and trace integrity.
- Safety-policy and approval-evidence integrity.
- Demo-session isolation and short-lived signing authority.
- Provider deployment authority and public artifact provenance.
- The absolute absence of network mutation capability.

## Trust boundaries

External JSON, browser input, MCP requests, alarm prose, workflow logs, cloud API responses, environment configuration, and imported evidence are untrusted. Each is parsed once into a closed typed contract. Private keys, provider tokens, and deployment credentials remain outside repository and artifact boundaries.

## Threats and controls

| Threat | Control | Failure behavior |
| --- | --- | --- |
| Alarm prompt injection alters a decision | Store prose as untrusted evidence; typed metrics and closed policy code own decisions | Reject/flag, never route prose to authority |
| Candidate changes mutate baseline or execute | Immutable baseline, typed patch allowlist, no command adapter, ADR 0002 | Fail before simulation/approval |
| Forged, replayed, expired, or cross-session approval | Root-certified Ed25519 session key, bound hashes/nonce/TTL, append-only state | Stable denial with evidence |
| Credential leaks through logs/reports | Hash/status-only receipts plus token/private-key scanners | Exit three and do not write accepted artifact |
| WIF confused deputy | Immutable GitHub owner ID, exact repository allowlist, exact issuer, principal-set bindings | Token exchange denied |
| Stale workflow accepted | Bind dispatch and waiter to exact bootstrap head SHA | Exit three |
| Temporary cloud resource remains | Unique names, snapshot/restore, finally/trap cleanup, explicit cleanup receipt | Preflight invalid |
| Misleading readiness | Ready iff every permission is proven and all cleanup is clean/restored | Blocked is valid; false ready is invalid |
| Supply-chain action drift | Pin workflow actions and dependency locks | CI refuses unreviewed drift |
| Synthetic data mistaken for production evidence | Prominent source/claim boundaries in artifacts and UI | No carrier-production claim |

## Residual risk

Todo 1 cannot exercise cloud-provider write and token-exchange paths without credentials. It therefore reports those authorities blocked and records the live path as not tested; it does not infer permission from configuration names.
