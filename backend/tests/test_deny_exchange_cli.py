from __future__ import annotations

from typing import TYPE_CHECKING

from telco_twin.bootstrap.deny_exchange_contract import DenyExchangeClassification

from .conftest import run_project_script
from .test_deny_exchange_classifier import PROVIDER_RESOURCE, PROVIDER_SNAPSHOT

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_writes_unproven_report_without_oidc_authority(tmp_path: Path) -> None:
    # Given
    provider = tmp_path / "provider.json"
    report = tmp_path / "classification.json"
    _ = provider.write_text(PROVIDER_SNAPSHOT, encoding="utf-8")

    # When
    result = run_project_script(
        "deny_exchange_probe.py",
        "--provider-json",
        str(provider),
        "--provider-resource",
        PROVIDER_RESOURCE,
        "--out",
        str(report),
        environment={
            "ACTIONS_ID_TOKEN_REQUEST_URL": "",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "",
        },
    )

    # Then
    assert result.returncode == 3
    classification = DenyExchangeClassification.model_validate_json(
        report.read_text(encoding="utf-8")
    )
    assert classification.status == "deny-exchange-rejection-unproven"


def test_cli_blocks_drifted_provider_before_oidc_request(tmp_path: Path) -> None:
    # Given
    provider = tmp_path / "provider.json"
    report = tmp_path / "classification.json"
    drifted = PROVIDER_SNAPSHOT.replace(
        "assertion.repository=='oyeong011/nonmatching-preflight'",
        "true",
    )
    _ = provider.write_text(drifted, encoding="utf-8")

    # When
    result = run_project_script(
        "deny_exchange_probe.py",
        "--provider-json",
        str(provider),
        "--provider-resource",
        PROVIDER_RESOURCE,
        "--out",
        str(report),
        environment={
            "ACTIONS_ID_TOKEN_REQUEST_URL": "https://unreachable.invalid/oidc",
            "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fabricated-request-value",
        },
    )

    # Then
    assert result.returncode == 3
    classification = DenyExchangeClassification.model_validate_json(
        report.read_text(encoding="utf-8")
    )
    assert classification.provider_verified is False
