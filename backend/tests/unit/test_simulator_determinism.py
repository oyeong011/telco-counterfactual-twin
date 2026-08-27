"""Cross-run simulator determinism and integrity tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from telco_twin.data.synthetic import SimulationManifest, generate_manifest
from telco_twin.simulator.engine import ManifestIntegrityError, run_simulation
from telco_twin.simulator.hashing import (
    EmptyTraceError,
    HashContext,
    TraceHashInput,
    hash_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_same_manifest_produces_one_nonempty_trace_hash_across_100_runs() -> None:
    # Given: one untouched versioned input manifest.
    manifest = generate_manifest(20260827)
    # When: the engine executes 100 independent runs.
    traces = tuple(run_simulation(manifest) for _ in range(100))
    # Then: every run is nonempty and content-hash identical.
    assert all(trace.events for trace in traces)
    assert tuple(trace.trace_hash for trace in traces) == (traces[0].trace_hash,) * 100


def test_same_manifest_is_byte_stable_across_isolated_processes(tmp_path: Path) -> None:
    # Given: one serialized manifest and two distinct process hash seeds.
    manifest_path = tmp_path / "manifest.json"
    _ = manifest_path.write_text(generate_manifest(71).model_dump_json(), encoding="utf-8")
    code = (
        "from pathlib import Path;"
        "from telco_twin.data.synthetic import SimulationManifest;"
        "from telco_twin.simulator.engine import run_simulation;"
        "import sys;"
        "manifest=SimulationManifest.model_validate_json(Path(sys.argv[1]).read_text());"
        "trace=run_simulation(manifest);"
        "print(trace.trace_hash)"
    )
    outputs: list[str] = []
    # When: independent interpreters execute with different PYTHONHASHSEED values.
    for hash_seed in ("1", "987654"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = hash_seed
        result = subprocess.run(
            [sys.executable, "-c", code, str(manifest_path)],
            cwd=REPO_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        outputs.append(result.stdout)
    # Then: the emitted trace hash bytes are identical.
    assert outputs == [outputs[0], outputs[0]]


def test_mutated_manifest_is_rejected_before_simulation() -> None:
    # Given: a valid manifest whose nested topology payload is changed after hashing.
    manifest = generate_manifest(11)
    manifest.topology.nodes[0].attributes["capacity_ues"] = 999
    # When: execution attempts to cross the integrity boundary.
    with pytest.raises(ManifestIntegrityError, match="simulation-manifest"):
        _ = run_simulation(manifest)
    # Then: no trace can be returned from the rejected input.


def test_stale_manifest_hash_is_rejected_before_simulation() -> None:
    # Given: an otherwise valid manifest carrying a stale content hash.
    manifest = generate_manifest(12).model_copy(update={"manifest_hash": "0" * 64})
    # When: execution attempts to cross the integrity boundary.
    with pytest.raises(ManifestIntegrityError, match="simulation-manifest"):
        _ = run_simulation(manifest)
    # Then: no stale manifest is accepted as replayable.


def test_manifest_boundary_rejects_unknown_input() -> None:
    # Given: valid manifest JSON with one unknown field injected.
    encoded = generate_manifest(13).model_dump_json()
    malformed = f'{encoded[:-1]},"unexpected":"value"}}'
    # When: the untrusted JSON crosses the Pydantic boundary.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _ = SimulationManifest.model_validate_json(malformed)
    # Then: the unknown input never reaches the engine.


def test_trace_hash_input_rejects_misleading_zero_event_success() -> None:
    # Given: a valid manifest hash with no simulator events.
    manifest_hash = generate_manifest(14).manifest_hash
    # When: a trace hash input is constructed without evidence events.
    with pytest.raises(EmptyTraceError, match="at least one event"):
        _ = TraceHashInput(
            manifest_hash=manifest_hash,
            events=(),
        )
    # Then: an empty run cannot receive a success hash.


def test_canonical_hash_binds_input_name_version_and_seed() -> None:
    # Given: one canonical topology and four distinct hash contexts.
    topology = generate_manifest(15).topology
    contexts = (
        HashContext(
            schema_version="1.0",
            input_name="topology",
            input_version="1.0.0",
            seed=15,
        ),
        HashContext(
            schema_version="1.0",
            input_name="scenario",
            input_version="1.0.0",
            seed=15,
        ),
        HashContext(
            schema_version="1.0",
            input_name="topology",
            input_version="1.0.1",
            seed=15,
        ),
        HashContext(
            schema_version="1.0",
            input_name="topology",
            input_version="1.0.0",
            seed=16,
        ),
    )
    # When: RFC 8785 boundary hashes are computed.
    digests = tuple(hash_contract(topology, context) for context in contexts)
    # Then: input identity, version, and seed are all digest-bearing.
    assert len(set(digests)) == len(contexts)
