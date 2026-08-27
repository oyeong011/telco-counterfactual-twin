# Schema Boundary

## Status

Todo 2 publishes canonical JSON Schemas generated from strict typed domain models.

## Validation boundary

`check-jsonschema` is the independent structural validator. It proves required fields, closed objects, scalar formats, patterns, lengths, and bounds. Plain JSON Schema cannot compare two RFC3339 timestamps to prove an exact 60-second duration, and it cannot fully tokenize arbitrary snake, kebab, and camel-case keys at every nesting depth.

Each generated schema therefore carries machine-readable `x-telco-twin-invariants` and `x-telco-twin-key-policy` annotations. Both declare `json_schema_support: annotation_only` and name `scripts/validate_contract.py` as their enforcing boundary. The project validator verifies those annotations match the source registry, then applies the Pydantic cross-field and recursive semantic-key rules. It is normative for TTL/window and semantic-key parity; it does not claim that a plain JSON Schema engine enforces unsupported comparisons.

The semantic-key policy evaluates both parsed snake/kebab/camel tokens and a lowercase alphanumeric collapsed form. This closes separator-free variants such as `subscriberid`, `customerid`, `shellcommand`, and `accesstoken` without substring-matching legitimate words such as `shellfish_count`, `tokenization_mode`, or `executioner_state`.

Approval descriptors and certificates expose public OKP JWKs only. Their `x` coordinate is exactly 32 bytes encoded as 43 unpadded base64url characters; private `d` is forbidden even when it has that canonical length. The committed test private key remains an unmistakably test-only PKCS#8 PEM. Ed25519 signatures are exactly 64 bytes/86 unpadded characters, and approval nonces are exactly 16 bytes/22 unpadded characters.

`trusted_root_hashes` is one SHA-256 digest of the canonical trust-root-set artifact, not an array of individual roots. A component with no applicable trust roots uses the required SHA-256 of exact bytes `{}\n`.

Both session certificates and approval proofs have an exact 60-second TTL. The proof interval must be contained by the certificate interval (`certificate.issued_at <= proof.approved_at` and `proof.expires_at <= certificate.expires_at`). Therefore the only valid boundary is an equal certificate/proof window; a proof starting even one second later necessarily ends one second outside the certificate. The approval-proof schema records this consequence in `x-telco-twin-certificate-window`, and the project validator is normative for it.
