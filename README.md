# Telco Counterfactual Twin

> **한국어 요약** — 통신망 설정 변경(patch)을 실제 망에 적용하기 전에, 결정론적 합성 트윈 안에서 baseline과 candidate를 반사실(counterfactual)로 비교하고, 안전 게이트를 통과한 경우에만 **서명된 승인 증거**를 남기는 시스템입니다. 승인은 자격을 기록할 뿐 패치를 집행하지 않습니다 — 이 저장소 어디에도 실제·모의 망을 변경하는 경로가 없습니다. 모든 수치는 커밋 SHA·명령·시드를 담은 생성 아티팩트에서만 나오며, README에 손으로 쓴 숫자는 없습니다. 아래 "무엇을 하지 않는가"를 먼저 읽어 주세요.

A deterministic synthetic twin for proving a proposed telecom change before an
evidence-only approval. It does not connect to an operator network, use customer
data, or expose any execution surface. Its second half,
[mcp-evidence-plane](https://github.com/oyeong011/mcp-evidence-plane), governs
how an agent is allowed to reach these tools at all.

## What it does

1. **Synthesises a 5G-shaped network** — cells/gNBs, UE cohorts, backhaul,
   AMF/SMF/UPF, slices, config history, alarms, telemetry — from a fixed seed
   with content hashes, so any run can be replayed byte for byte.
2. **Diagnoses six held-out fault families** — radio congestion, backhaul
   degradation, UPF saturation, neighbour/handover misconfiguration, slice
   scheduler misallocation, and alarm prompt injection. When symptoms overlap
   and the closed rules must abstain, the twin simulates each family alone and
   keeps the hypothesis nearest the observation.
3. **Projects a patch before approval** — baseline versus candidate, blast
   radius and constraint checks, and a collateral coupling per sized operation:
   more radio capacity loads the core, restored backhaul admits more traffic to
   the core, more UPF units draw site power, and one slice's weight starves its
   peer.
4. **Records an approval as evidence** — signed, hash-bound, replayable. Never
   as authority to act.

## Numbers, and exactly where they come from

Every figure below is read from a committed artifact that names the source
commit, the command, and the seed that produced it. Regenerate with
`make generate-release-evidence`; the verifier refuses evidence whose source
commit does not match.

**Diagnosis, v2 difficulty corpus** — `artifacts/eval-v2/diagnosis-v2.json`,
source `4aa82fa`, seed `20270827`, measurement noise `0.12`, 144 cases,
72 held out.

| tier (18 held-out cases each) | rules-only | twin |
| --- | --- | --- |
| clean | 16 | 18 |
| near-threshold | 7 | 18 |
| masked | 5 | 16 |
| confounded | 15 | 18 |
| **macro F1** | **0.733** | **0.972** |

The v1 corpus scored 1.0 on both arms. That was not an achievement: every v1
case tripped exactly one rule, and the twin arm was the rules plus an
abstention, so the two could never diverge. The v2 tiers and the counterfactual
disambiguation exist to make the number capable of being wrong.

**Safety, v2 tiered corpus** — same artifact, `safety` section. 80 cases: four
sized operations × five tiers × four noise draws. Expectations come from the
noiseless truth; the gate only ever sees a noisy observation.

| gate | unsafe blocked | safe false blocks |
| --- | --- | --- |
| bounds-only (parameter range, blast radius, hashes) | **0 / 32** | 0 / 48 |
| SLO projection | 24 / 32 | 4 / 48 |

The shipped bounds block none of the unsafe patches, because every one of them
satisfies every bound and still breaches an unrelated SLO. That blind spot is
the reason the projection gate exists, and the gate is deliberately imperfect
in at least one direction for every operation.

## What it does not do — read before judging

- **All data is synthetic.** No operator, customer, or live-network data.
  "Real-time" never applies here.
- **The twin holds the same forward model that generated each case.**
  Measurement noise is the only source of mismatch, so 0.972 is an optimistic
  ceiling and does not demonstrate transfer to a real network.
- **No execution authority, real or simulated.** Approval records eligibility.
- **Each safety coupling is one declared constant per operation**
  (for example 0.225 CPU points per UE slot, 0.7 kW per UPF unit), not a
  physical measurement. The two boolean operations are unmodeled, not faked.
- **The LLM comparison arm is `not_run`** — no exact model snapshot was
  available, so no three-arm comparison is claimed.
- **Much of the implementation was produced with AI coding agents** under
  human-set specifications, boundaries, and review. Ask about ownership and
  that is the answer.

## Verify it yourself

```bash
make verify                      # specs, lint, types, tests, contracts, evidence drift
make generate-release-evidence   # rebuilds every artifact from HEAD; needs Docker
```

CI runs the same gates on every push and pull request, including a live
Docker Compose probe and a check that no committed number drifts from the
source commit it claims.

## Layout

| path | what |
| --- | --- |
| `backend/src/telco_twin/simulator` | seeded topology, event scheduler, forward metric model |
| `backend/src/telco_twin/eval` | v1 frozen corpus, v2 difficulty corpus, disambiguation, scoring |
| `backend/src/telco_twin/safety` | SLO projection and the per-operation remediation models |
| `backend/src/telco_twin/{counterfactual,approval,mcp,api}` | patch fork, comparison, evidence, non-executing tools |
| `frontend/` | React operations console |
| `specs/` | PRD, test spec, API contract, threat model, JSON Schemas |
| `artifacts/` | generated evidence only, never edited by hand |

## Source and claim boundaries

- All topology, telemetry, alarms, users, and scenarios are synthetic.
- Benchmark values appear only when generated by the pinned repository commit
  and command recorded in an artifact.
- Approval is an evidence state; it is not authorization to mutate a real or
  simulated network.
