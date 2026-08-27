from __future__ import annotations

import json
from typing import TYPE_CHECKING

from telco_twin.bootstrap.preflight_contract import EXPECTED_PERMISSIONS

from .conftest import run_project_script

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic import JsonValue

BOOTSTRAP_SHA = "a" * 40
RECEIPT = "sha256:" + ("b" * 64)


def run_blocked_report(repo_root: Path, output_path: Path) -> None:
    result = run_project_script(
        "deployment_preflight.py",
        "--bootstrap-sha",
        BOOTSTRAP_SHA,
        "--report",
        "--offline",
        "--repo-root",
        str(repo_root),
        "--out",
        str(output_path),
        environment={
            "CLOUDFLARE_API_TOKEN": "fabricated-cloudflare-secret-value",
            "NEON_API_KEY": "fabricated-neon-secret-value",
        },
    )
    assert result.returncode == 0, result.stderr


def test_reports_blocked_without_leaking_environment_credentials(
    clean_git_repo: Path,
) -> None:
    # Given
    report_path = clean_git_repo / ".git" / "preflight.json"

    # When
    run_blocked_report(clean_git_repo, report_path)
    report_text = report_path.read_text(encoding="utf-8")
    validation = run_project_script(
        "deployment_preflight.py",
        "--validate",
        str(report_path),
        "--offline",
        "--repo-root",
        str(clean_git_repo),
    )

    # Then
    assert validation.returncode == 0, validation.stderr
    assert '"outcome": "deployment-blocked"' in report_text
    assert '"status": "blocked"' in report_text
    assert "fabricated-cloudflare-secret-value" not in report_text
    assert "fabricated-neon-secret-value" not in report_text


def test_rejects_token_like_value_before_schema_parsing(tmp_path: Path) -> None:
    # Given
    leaked = tmp_path / "leaked.json"
    _ = leaked.write_text(
        '{"authorization":"Bearer fabricated-token-value-0123456789"}\n',
        encoding="utf-8",
    )

    # When
    result = run_project_script("deployment_preflight.py", "--validate", str(leaked))

    # Then
    assert result.returncode == 3
    assert "secret-like-value" in result.stderr


def test_parses_explicit_blocked_provider_status(tmp_path: Path) -> None:
    # Given
    provider = tmp_path / "provider.json"
    _ = provider.write_text(
        f"""{{
  "provider": "github",
  "status": "blocked",
  "permissions": [
    {{"permission":"repo.public","granted":false,"status":"blocked","evidence":"{RECEIPT}"}},
    {{"permission":"workflow.read","granted":false,"status":"blocked","evidence":"{RECEIPT}"}},
    {{"permission":"workflow.dispatch","granted":false,"status":"blocked","evidence":"{RECEIPT}"}},
    {{"permission":"repo.admin","granted":false,"status":"blocked","evidence":"{RECEIPT}"}}
  ],
  "blockers": ["offline-mode"],
  "cleanup": "not-created",
  "evidence": "{RECEIPT}"
}}\n""",
        encoding="utf-8",
    )

    # When
    result = run_project_script(
        "deployment_preflight.py",
        "--validate-provider",
        str(provider),
    )

    # Then
    assert result.returncode == 0, result.stderr


def test_rejects_malformed_provider_json(tmp_path: Path) -> None:
    # Given
    provider = tmp_path / "malformed-provider.json"
    _ = provider.write_text('{"provider":"github","status":42}\n', encoding="utf-8")

    # When
    result = run_project_script(
        "deployment_preflight.py",
        "--validate-provider",
        str(provider),
    )

    # Then
    assert result.returncode == 3
    assert "invalid-provider-report" in result.stderr


def test_rejects_ready_provider_when_permission_is_unproven(tmp_path: Path) -> None:
    # Given
    provider = tmp_path / "misleading-provider.json"
    _ = provider.write_text(
        f"""{{
  "provider": "github",
  "status": "ready",
  "permissions": [
    {{"permission":"repo.public","granted":false,"status":"blocked","evidence":"{RECEIPT}"}},
    {{"permission":"workflow.read","granted":true,"status":"ready","evidence":"{RECEIPT}"}},
    {{"permission":"workflow.dispatch","granted":true,"status":"ready","evidence":"{RECEIPT}"}},
    {{"permission":"repo.admin","granted":true,"status":"ready","evidence":"{RECEIPT}"}}
  ],
  "blockers": [],
  "cleanup": "clean",
  "evidence": "{RECEIPT}"
}}\n""",
        encoding="utf-8",
    )

    # When
    result = run_project_script(
        "deployment_preflight.py",
        "--validate-provider",
        str(provider),
    )

    # Then
    assert result.returncode == 3
    assert "provider-status-inconsistent" in result.stderr


def test_rejects_misleading_ready_report_without_authority(
    clean_git_repo: Path,
    tmp_path: Path,
) -> None:
    # Given
    report_path = tmp_path / "misleading-ready.json"
    run_blocked_report(clean_git_repo, report_path)
    original = report_path.read_text(encoding="utf-8")
    misleading = original.replace(
        '"outcome": "deployment-blocked"',
        '"outcome": "deployment-ready"',
        1,
    )
    assert misleading != original
    _ = report_path.write_text(misleading, encoding="utf-8")

    # When
    result = run_project_script("deployment_preflight.py", "--validate", str(report_path))

    # Then
    assert result.returncode == 3
    assert "report-outcome-inconsistent" in result.stderr


def test_rejects_unsupported_cost_control_setting(
    clean_git_repo: Path,
    tmp_path: Path,
) -> None:
    # Given
    report_path = tmp_path / "unsupported-cost.json"
    run_blocked_report(clean_git_repo, report_path)
    original = report_path.read_text(encoding="utf-8")
    unsupported = original.replace("preflight-only", "unsupported", 1)
    assert unsupported != original
    _ = report_path.write_text(unsupported, encoding="utf-8")

    # When
    result = run_project_script("deployment_preflight.py", "--validate", str(report_path))

    # Then
    assert result.returncode == 3
    assert "invalid-preflight-report" in result.stderr


def test_rejects_fully_shape_valid_fabricated_ready_report(
    clean_git_repo: Path,
) -> None:
    # Given
    report_path = clean_git_repo / ".git" / "forged-ready.json"
    providers: list[JsonValue] = []
    for provider, permissions in EXPECTED_PERMISSIONS.items():
        providers.append(
            {
                "provider": provider,
                "status": "ready",
                "permissions": [
                    {
                        "permission": permission,
                        "granted": True,
                        "status": "ready",
                        "evidence": RECEIPT,
                    }
                    for permission in permissions
                ],
                "blockers": [],
                "cleanup": "clean",
                "evidence": RECEIPT,
                "authority": {
                    "identities": [f"forged/{provider}"],
                    "request_hashes": [RECEIPT],
                    "response_hashes": [RECEIPT],
                    "command_hashes": [RECEIPT],
                },
            }
        )
    forged: dict[str, JsonValue] = {
        "schema_version": "1.0",
        "generated_at": "2026-08-27T00:00:00Z",
        "bootstrap_sha": BOOTSTRAP_SHA,
        "outcome": "deployment-ready",
        "cost_control": "preflight-only",
        "repository": {
            "repository": "oyeong011/telco-counterfactual-twin",
            "local_worktree_clean": True,
            "remote_main_matches_bootstrap": True,
            "public_nonfork_main_mit": True,
            "workflow_active": True,
            "evidence": RECEIPT,
        },
        "providers": providers,
        "temporary_resources": [],
        "report_evidence": RECEIPT,
    }
    _ = report_path.write_text(json.dumps(forged), encoding="utf-8")

    # When
    result = run_project_script(
        "deployment_preflight.py",
        "--validate",
        str(report_path),
        "--repo-root",
        str(clean_git_repo),
    )

    # Then
    assert result.returncode == 3
    assert "ready-authority-mismatch" in result.stderr
