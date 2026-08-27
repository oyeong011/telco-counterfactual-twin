"""Cross-run simulator determinism and integrity tests."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from telco_twin.data.synthetic import SimulationManifest, generate_manifest
from telco_twin.domain.event import Event
from telco_twin.simulator.engine import ManifestIntegrityError, run_simulation
from telco_twin.simulator.frozen_event import FrozenEvent
from telco_twin.simulator.hashing import (
    EmptyTraceError,
    HashContext,
    TraceHashInput,
    hash_contract,
    hash_trace,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

INVALID_EVENT_CASES = (
    (
        (
            '{"event_id":"event-0001","scenario_id":"scenario-0001",'
            '"timestamp":"2026-08-27T00:00:00Z","priority":0,"sequence_id":1,'
            '"event_type":"parser-test","payload":{"nested":{"x":1}},"schema_version":"1.0"}'
        ),
        "string_type",
    ),
    (
        (
            '{"event_id":"event-0001","scenario_id":"scenario-0001",'
            '"timestamp":"2026-08-27T00:00:00Z","priority":1001,"sequence_id":1,'
            '"event_type":"parser-test","payload":{"count":1},"schema_version":"1.0"}'
        ),
        "less_than_equal",
    ),
    (
        (
            '{"event_id":"event-0001","scenario_id":"scenario-0001",'
            '"timestamp":"2026-08-27T00:00:00Z","priority":0,"sequence_id":1,'
            '"event_type":"parser-test","payload":{"count":1},"unexpected":"x",'
            '"schema_version":"1.0"}'
        ),
        "extra_forbidden",
    ),
    (
        (
            '{"event_id":"event-0001","scenario_id":"scenario-0001",'
            '"timestamp":"2026-08-27T00:00:00Z","priority":0,"sequence_id":1,'
            '"event_type":"parser-test","payload":{"count":1},"extensions":'
            '{"schema_version":"1.0","values":{"nested":{"x":1}}},"schema_version":"1.0"}'
        ),
        "string_type",
    ),
)


def test_same_manifest_produces_one_nonempty_trace_hash_across_100_runs() -> None:
    # Given: one untouched versioned input manifest.
    manifest = generate_manifest(20260827)
    # When: the engine executes 100 independent runs.
    traces = tuple(run_simulation(manifest) for _ in range(100))
    # Then: every run is nonempty and content-hash identical.
    assert all(trace.events for trace in traces)
    assert tuple(trace.trace_hash for trace in traces) == (traces[0].trace_hash,) * 100


def test_exposed_trace_payload_rejects_mutation_and_keeps_canonical_hash() -> None:
    # Given: a completed trace and independent canonical hash context.
    manifest = generate_manifest(20260827)
    trace = run_simulation(manifest)
    context = HashContext(
        schema_version="1.0",
        input_name="simulation-trace",
        input_version="1.0.0",
        seed=manifest.seed,
    )
    before = hash_trace(
        TraceHashInput(manifest_hash=trace.manifest_hash, events=trace.events),
        context,
    )
    # When: a caller attempts to mutate the returned event payload.
    with pytest.raises(TypeError, match="immutable"):
        trace.events[0].payload["manifest_hash"] = "0" * 64
    after = hash_trace(
        TraceHashInput(manifest_hash=trace.manifest_hash, events=trace.events),
        context,
    )
    # Then: the stored hash remains an independent recomputation of exposed events.
    assert trace.trace_hash == before == after


@pytest.mark.parametrize(("encoded", "expected_code"), INVALID_EVENT_CASES)
def test_frozen_event_parser_uses_authoritative_event_boundary(
    encoded: str,
    expected_code: str,
) -> None:
    # Given: JSON invalid under the authoritative Event contract.
    # When: both public parsers receive the same untrusted JSON.
    with pytest.raises(ValidationError) as event_error:
        _ = Event.model_validate_json(encoded)
    with pytest.raises(ValidationError) as frozen_error:
        _ = FrozenEvent.model_validate_json(encoded)
    # Then: the snapshot parser preserves the stable Event error code.
    assert expected_code in {item["type"] for item in event_error.value.errors()}
    assert expected_code in {item["type"] for item in frozen_error.value.errors()}


def test_same_manifest_is_byte_stable_across_isolated_processes(tmp_path: Path) -> None:
    # Given: one serialized manifest and two distinct process hash seeds.
    manifest_path = tmp_path / "manifest.json"
    _ = manifest_path.write_text(generate_manifest(71).model_dump_json(), encoding="utf-8")
    code = (
        "from pathlib import Path;"
        "from telco_twin.data.synthetic import SimulationManifest;"
        "from telco_twin.domain._contract import VersionedExtensions;"
        "from telco_twin.domain.event import Event;"
        "from telco_twin.simulator.engine import run_simulation;"
        "from telco_twin.simulator.hashing import HashContext,TraceHashInput,hash_trace;"
        "from telco_twin.simulator.scheduler import DeterministicScheduler;"
        "import sys;"
        "manifest=SimulationManifest.model_validate_json(Path(sys.argv[1]).read_text());"
        "trace=run_simulation(manifest);"
        "source=Event(event_id='event-0099',scenario_id='scenario-0001',"
        "timestamp='2026-08-27T00:00:00Z',priority=0,sequence_id=99,"
        "event_type='extension-test',payload={'count':1},"
        "extensions=VersionedExtensions(schema_version='1.0',"
        "values={'flag':'original'}),schema_version='1.0');"
        "scheduler=DeterministicScheduler();scheduler.schedule(source);"
        "stored=scheduler.drain().events[0];"
        "context=HashContext(schema_version='1.0',input_name='simulation-trace',"
        "input_version='1.0.0',seed=71);"
        "extension_hash=hash_trace(TraceHashInput("
        "manifest_hash=manifest.manifest_hash,events=(stored,)),context);"
        "print(trace.trace_hash+':'+extension_hash+':'+stored.model_dump_json())"
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
