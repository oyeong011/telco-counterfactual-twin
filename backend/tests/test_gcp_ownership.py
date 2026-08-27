from __future__ import annotations

import re

import pytest

from telco_twin.bootstrap.gcp_commands import GcpContext, ProvisioningError
from telco_twin.bootstrap.gcp_ownership import (
    MANAGED_BY_MARKER,
    OperationOwnership,
    RunOwnership,
)
from telco_twin.bootstrap.gcp_resource_contract import TopicRollbackIntent, TopicSnapshot

CONTEXT = GcpContext("example-project", "987654321", "ABC", "12345678")


def test_run_ownership_derives_stable_distinct_operation_fingerprints() -> None:
    # Given
    run = RunOwnership(b"a" * 32)

    # When
    topic = run.for_operation("topic")
    same_topic = run.for_operation("topic")
    budget = run.for_operation("budget")
    other_run = RunOwnership(b"b" * 32).for_operation("topic")

    # Then
    assert topic == same_topic
    assert topic != budget
    assert topic != other_run
    assert re.fullmatch(r"[0-9a-z]{25}", topic.fingerprint)
    assert topic.marker == f"{MANAGED_BY_MARKER};op={topic.fingerprint}"
    assert len(topic.marker) == 60


@pytest.mark.parametrize(
    "fingerprint",
    ["", "a" * 24, "a" * 26, "A" * 25, "_" * 25, "!" * 25],
)
def test_operation_ownership_rejects_malformed_fingerprint(fingerprint: str) -> None:
    # Given / When / Then
    with pytest.raises(ProvisioningError, match="operation-fingerprint-invalid"):
        _ = OperationOwnership(fingerprint)


def test_generated_run_id_uses_cryptographic_random_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    calls: list[int] = []

    def token_bytes(size: int) -> bytes:
        calls.append(size)
        return b"c" * size

    monkeypatch.setattr("telco_twin.bootstrap.gcp_ownership.secrets.token_bytes", token_bytes)

    # When
    ownership = RunOwnership.generate().for_operation("service-account")

    # Then
    assert calls == [32]
    assert re.fullmatch(r"[0-9a-z]{25}", ownership.fingerprint)


@pytest.mark.parametrize("fingerprint", ["b" * 25, "malformed-fingerprint"])
def test_resource_match_rejects_collision_or_malformed_fingerprint(
    fingerprint: str,
) -> None:
    # Given
    ownership = OperationOwnership("a" * 25)
    intent = TopicRollbackIntent(CONTEXT, "twin-preflight-test", ownership)
    snapshot = TopicSnapshot(
        name="projects/example-project/topics/twin-preflight-test",
        labels={
            "managed-by": "telco-twin-preflight",
            "operation-fingerprint": fingerprint,
        },
    )

    # When
    matches = intent.matches(snapshot)

    # Then
    assert matches is False
