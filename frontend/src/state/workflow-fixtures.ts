import {
  ApprovalRequestResponseSchema,
  ComparisonResponseSchema,
  DemoSessionResponseSchema,
  DiagnosisResponseSchema,
  PatchResponseSchema,
  ScenarioResponseSchema,
  SimulationResponseSchema,
} from "../contracts/generated"
import type { SessionStorageLike } from "./session"

export const HASH = "a".repeat(64)

export class FakeStorage implements SessionStorageLike {
  private readonly values = new Map<string, string>()

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }
}

export const session = DemoSessionResponseSchema.parse({
  session_id: "session-001",
  demo_token: "demo-token-secret",
  session_certificate: {
    session_id: "session-001",
    session_key_id: "session-key-001",
    session_public_key_jwk: { kty: "OKP", crv: "Ed25519", x: "A".repeat(43) },
    root_key_id: "root-key-001",
    issued_at: "2026-08-28T00:00:00Z",
    expires_at: "2026-08-28T00:01:00Z",
    environment: "test",
    certificate_signature: "A".repeat(86),
    schema_version: "1.0",
  },
  expires_at: "2026-08-28T00:01:00Z",
  startup_epoch: "epoch-001",
  durability: "process-memory",
  synthetic_only: true,
})

export const scenario = ScenarioResponseSchema.parse({
  scenario: {
    schema_version: "1.0",
    scenario_id: "scenario-001",
    topology_id: "topology-001",
    seed: 6701,
    fault_family: "radio-congestion",
    starts_at: "2026-08-28T00:00:00Z",
    duration_seconds: 300,
    target_ids: ["cell-0001"],
    parameters: {},
  },
  topology_hash: HASH,
  scenario_hash: HASH,
  run_id: "run-001",
})

export const diagnosis = DiagnosisResponseSchema.parse({
  scenario_id: "scenario-001",
  run_id: "run-001",
  status: "primary",
  primary_fault: "radio-congestion",
  secondary_evidence: [],
})

export const patch = PatchResponseSchema.parse({
  patch: {
    schema_version: "1.0",
    patch_id: "patch-001",
    scenario_id: "scenario-001",
    base_topology_hash: HASH,
    changes: [
      {
        target_id: "cell-0001",
        target_kind: "cell",
        operation: "adjust-radio-capacity",
        parameters: { capacity_ues: 230 },
      },
    ],
    blast_radius: { max_cells: 1, max_ue_cohorts: 1, max_slices: 1 },
    proposed_at: "2026-08-28T00:00:00Z",
  },
  patch_hash: HASH,
  run_id: "run-001",
})

export const simulation = SimulationResponseSchema.parse({
  simulation_id: "simulation-001",
  scenario_id: "scenario-001",
  patch_id: "patch-001",
  run_id: "run-001",
  status: "completed",
  trace_hash: HASH,
})

export const comparison = ComparisonResponseSchema.parse({
  comparison_id: "comparison-001",
  run_id: "run-001",
  comparison: {
    result: {
      schema_version: "1.0",
      simulation_id: "simulation-001",
      scenario_id: "scenario-001",
      patch_hash: HASH,
      baseline_hash: HASH,
      candidate_hash: HASH,
      trace_hash: HASH,
      started_at: "2026-08-28T00:00:00Z",
      completed_at: "2026-08-28T00:00:00Z",
      metric_deltas: [{ metric_name: "throughput", baseline: 100, candidate: 120, unit: "mbps" }],
      constraints: [{ constraint_code: "safe", passed: true, evidence_hash: HASH }],
      approval_eligible: true,
    },
    evidence_hashes: {
      patch_hash: HASH,
      baseline_manifest_hash: HASH,
      candidate_manifest_hash: HASH,
      baseline_trace_hash: HASH,
      candidate_trace_hash: HASH,
      constraint_set_hash: HASH,
    },
  },
})

export const approval = ApprovalRequestResponseSchema.parse({
  approval_request: {
    request_id: "approval-request-001",
    session_id: "session-001",
    patch_hash: HASH,
    simulation_hash: HASH,
    policy_hash: HASH,
    nonce: "A".repeat(22),
    requested_at: "2026-08-28T00:00:00Z",
    expires_at: "2026-08-28T00:01:00Z",
    state: "pending",
    schema_version: "1.0",
  },
  policy: {
    eligible: true,
    reasons: [],
    patch_hash: HASH,
    simulation_hash: HASH,
    quality_hash: HASH,
    policy_definition_hash: HASH,
    policy_hash: HASH,
  },
  run_id: "run-001",
  evidence_id: "evidence-001",
})
