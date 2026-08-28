"""Bounded real-simulator benchmark route implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from telco_twin.api.contracts import BenchmarkRequest, BenchmarkResponse
from telco_twin.api.mutations import EvidenceAppend, append_mutation, stable_id
from telco_twin.data.synthetic import generate_manifest
from telco_twin.simulator.engine import run_simulation

if TYPE_CHECKING:
    from telco_twin.api.runtime import ApiRuntime, AuthorizedSession


@final
class BenchmarkLifecycle:
    """Run an honest determinism smoke probe without model-evaluation claims."""

    def __init__(self, runtime: ApiRuntime) -> None:
        """Bind the benchmark to one process runtime."""
        self._runtime = runtime

    async def run(
        self,
        authorized: AuthorizedSession,
        idempotency_key: str,
        request: BenchmarkRequest,
    ) -> tuple[BenchmarkResponse, bool]:
        """Run the requested number of real deterministic simulator calls."""
        session = authorized.session
        result_id = stable_id("benchmark", session.session_id, idempotency_key)
        run_id = stable_id("run", session.session_id, idempotency_key)
        async with session.lock:
            mutation = await append_mutation(
                self._runtime,
                authorized,
                EvidenceAppend(
                    idempotency_key=idempotency_key,
                    event_type="benchmark-completed",
                    body=request,
                    scenario_id="scenario-benchmark",
                    run_id=run_id,
                    resource_id=result_id,
                ),
            )
            hashes = tuple(
                run_simulation(generate_manifest(request.seed)).trace_hash
                for _ in range(request.iterations)
            )
            unique = frozenset(hashes)
            return (
                BenchmarkResponse(
                    seed=request.seed,
                    iterations=request.iterations,
                    unique_trace_hashes=len(unique),
                    deterministic=len(unique) == 1,
                    trace_hash=hashes[0],
                ),
                mutation.replayed,
            )
