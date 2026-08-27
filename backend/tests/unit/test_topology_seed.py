"""Seeded synthetic-topology contract tests."""

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from telco_twin.data.synthetic import generate_manifest
from telco_twin.domain.topology import MAX_CELLS, MIN_CELLS, NodeKind

MAX_SEED = (2**53) - 1


@settings(max_examples=100, derandomize=True, deadline=None)
@given(seed=st.integers(min_value=0, max_value=MAX_SEED))
def test_generated_topology_preserves_telco_bounds_when_seed_varies(seed: int) -> None:
    # Given: one of 100 isolated simulator seeds.
    # When: a complete versioned manifest is generated.
    manifest = generate_manifest(seed)
    topology = manifest.topology
    kinds = tuple(node.kind for node in topology.nodes)
    node_ids = tuple(node.node_id for node in topology.nodes)
    # Then: every required synthetic family and bound is present.
    cell_count = kinds.count(NodeKind.CELL)
    assert MIN_CELLS <= cell_count <= MAX_CELLS
    assert kinds.count(NodeKind.GNB) == cell_count
    assert kinds.count(NodeKind.UE_COHORT) == cell_count
    assert all(kind in kinds for kind in NodeKind)
    assert all(link.source_id in node_ids and link.target_id in node_ids for link in topology.links)
    assert topology.config_history
    assert manifest.seed == topology.seed == manifest.scenario.seed
    assert manifest.scenario.topology_id == topology.topology_id
    assert manifest.schema_version == "1.0"
    assert manifest.input_version == "1.0.0"
    assert len(manifest.topology_hash) == len(manifest.scenario_hash) == 64
    assert len(manifest.manifest_hash) == 64


@settings(max_examples=100, derandomize=True, deadline=None)
@given(
    left_seed=st.integers(min_value=0, max_value=MAX_SEED - 1),
    offset=st.integers(min_value=1, max_value=10_000),
)
def test_topology_hash_changes_when_seed_changes(left_seed: int, offset: int) -> None:
    # Given: two distinct bounded seeds.
    right_seed = (left_seed + offset) % (MAX_SEED + 1)
    # When: their manifests are generated independently.
    left = generate_manifest(left_seed)
    right = generate_manifest(right_seed)
    # Then: topology identity changes while both models retain their invariants.
    assert left_seed != right_seed
    assert left.topology_hash != right.topology_hash
    right_cell_count = sum(node.kind is NodeKind.CELL for node in right.topology.nodes)
    assert MIN_CELLS <= right_cell_count <= MAX_CELLS


def test_same_seed_generates_one_manifest_hash_across_100_repeats() -> None:
    # Given: a fixed isolated seed.
    # When: the generator is invoked 100 independent times.
    manifest_hashes = tuple(generate_manifest(20260827).manifest_hash for _ in range(100))
    # Then: every versioned input manifest is byte-identical by digest.
    assert manifest_hashes == (manifest_hashes[0],) * 100


def test_generator_does_not_consume_global_random_state() -> None:
    # Given: an arbitrary global random state snapshot.
    state_before = random.getstate()
    # When: the isolated seeded generator runs.
    _ = generate_manifest(19)
    # Then: the process-global RNG remains untouched.
    assert random.getstate() == state_before
