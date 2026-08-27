"""Required stable negative scenarios for the Task5 manual probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from telco_twin.counterfactual.patches import PatchRejected, assess_patch
from telco_twin.counterfactual.runner import run_counterfactual
from telco_twin.domain.approval import (
    ContractViolationError,
    validate_approval_chain,
)
from telco_twin.safety.local_policy import LocalPolicyInput, evaluate_local_policy
from telco_twin.simulator.engine import ManifestIntegrityError
from telco_twin.state.memory_store import DemoSessionStore
from telco_twin.state.probe_evidence import NegativeEvidence
from telco_twin.state.store_models import SessionAccess, SessionAccessDenied
from telco_twin.state.trusted_clock import FixedClock

from scripts.task5_probe_flow_types import ProbeNegativeInputs
from scripts.task5_probe_support import (
    DEMO_KEY,
    ProbeInvariantCode,
    ProbeInvariantError,
    probe_approval_negatives,
)

if TYPE_CHECKING:
    from telco_twin.safety.local_policy import PolicyEvaluation


@dataclass(frozen=True, slots=True)
class _PolicyNegatives:
    stale: PolicyEvaluation
    missing: PolicyEvaluation


def _policy_negatives(inputs: ProbeNegativeInputs) -> _PolicyNegatives:
    stale = evaluate_local_policy(
        inputs.scenario.policy_input,
        FixedClock(inputs.scenario.stale_time),
    ).evidence
    missing = evaluate_local_policy(
        LocalPolicyInput(
            observation=inputs.scenario.policy_input.observation,
            quality_policy=inputs.scenario.policy_input.quality_policy,
            run=None,
            comparison=None,
        ),
        inputs.store.clock,
    ).evidence
    return _PolicyNegatives(stale, missing)


async def collect_negative_evidence(inputs: ProbeNegativeInputs) -> NegativeEvidence:
    """Execute every real negative and require stable typed outcomes."""
    unsafe_change = inputs.scenario.patch.changes[0].model_copy(
        update={"parameters": {"capacity_ues": 1001}}
    )
    unsafe = assess_patch(
        inputs.scenario.patch.model_copy(update={"changes": (unsafe_change,)}),
        inputs.scenario.manifest,
    )
    if not isinstance(unsafe, PatchRejected):
        raise ProbeInvariantError(ProbeInvariantCode.UNSAFE_REJECTION)
    policies = _policy_negatives(inputs)
    forged_code = "missing"
    try:
        validate_approval_chain(
            inputs.approval.proof.model_copy(update={"proof_signature": "A" * 86}),
            inputs.approval.context,
        )
    except ContractViolationError as error:
        forged_code = error.code.value
    replay_code = "missing"
    try:
        _ = await inputs.approval.machine.record_proof(inputs.approval.proof)
    except ContractViolationError as error:
        replay_code = error.code.value
    restarted = DemoSessionStore(
        signing_key=DEMO_KEY,
        startup_epoch="epoch-probe-0002",
        clock=inputs.store.clock,
    )
    epoch = await restarted.access(SessionAccess(token=inputs.store.token))
    malformed = await inputs.store.store.access(SessionAccess(token="malformed"))
    dirty = inputs.scenario.manifest.model_copy(deep=True)
    dirty.topology.nodes[0].attributes["capacity_ues"] = 999
    dirty_code = "missing"
    try:
        _ = run_counterfactual(dirty, inputs.scenario.patch)
    except ManifestIntegrityError:
        dirty_code = "manifest-integrity"
    if not isinstance(epoch, SessionAccessDenied) or not isinstance(
        malformed, SessionAccessDenied
    ):
        raise ProbeInvariantError(ProbeInvariantCode.NEGATIVE_SESSION)
    approval = probe_approval_negatives(
        inputs.approval.proof,
        inputs.approval.context,
        inputs.approval.authority,
    )
    return NegativeEvidence(
        replay_code=replay_code,
        epoch_code=epoch.code.value,
        malformed_code=malformed.code.value,
        unsafe_patch_code=unsafe.code.value,
        stale_policy_code=",".join(item.value for item in policies.stale.reasons),
        unsimulated_policy_code=",".join(
            item.value for item in policies.missing.reasons
        ),
        forged_proof_code=forged_code,
        dirty_baseline_code=dirty_code,
        expired_proof_code=approval.expired,
        cross_session_code=approval.cross_session,
    )
