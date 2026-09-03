from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER = REPO_ROOT / "scripts/scan_synthetic_boundary.py"


def run_scanner(*roots: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), *(str(root) for root in roots)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_repository_safe_roots_pass_without_findings() -> None:
    # Given: the repository roots expected to contain only synthetic-safe source assets.
    roots = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "backend/src",
        REPO_ROOT / "frontend/src",
        REPO_ROOT / "specs",
        REPO_ROOT / "scripts",
    )
    # When: the scanner inspects the declared source roots.
    result = run_scanner(*roots)
    # Then: no finding is emitted and the summary count stays zero.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic_boundary_findings=0" in result.stdout


def test_scanner_rejects_nested_json_personal_identifiers_without_leaking_values(
    tmp_path: Path,
) -> None:
    # Given: nested JSON carrying several real-looking personal identifiers.
    fixture = tmp_path / "unsafe.json"
    unsafe_payload = json.dumps(
        {
            "subscriber": {
                "msisdn": "010-9876-5432",
                "imsi": "450081234567890",
            },
            "profile": {
                "email": "person@gmail.com",
                "ip": "8.8.8.8",
            },
            "token": "sk-proj-supersecretsecretsecretsecret",
        },
        separators=(",", ":"),
    )
    _ = fixture.write_text(unsafe_payload, encoding="utf-8")
    # When: the scanner parses the JSON boundary.
    result = run_scanner(fixture)
    # Then: findings are structured by path and kind, and raw secrets are not echoed back.
    assert result.returncode == 1
    assert (
        "synthetic-boundary-finding:path=unsafe.json;kind=msisdn;location=$.subscriber.msisdn"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=unsafe.json;kind=imsi;location=$.subscriber.imsi"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=unsafe.json;kind=email;location=$.profile.email"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=unsafe.json;kind=ipv4;location=$.profile.ip"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=unsafe.json;kind=secret;location=$.token" in result.stdout
    )
    assert "person@gmail.com" not in result.stdout
    assert "sk-proj-supersecretsecretsecretsecret" not in result.stdout
    assert "synthetic_boundary_findings=5" in result.stdout


def test_scanner_allows_documented_synthetic_examples_and_service_accounts(
    tmp_path: Path,
) -> None:
    # Given: documented synthetic values, hash-like IDs, and service-account addresses.
    fixture = tmp_path / "safe.json"
    safe_payload = json.dumps(
        {
            "host": "127.0.0.1",
            "email": "qa@example.invalid",
            "hash": "a" * 64,
            "topology_id": "cell-0001",
            "service_account": ("skt-portfolio-deployer@example-project.iam.gserviceaccount.com"),
            "documentation_ip": "203.0.113.42",
        },
        separators=(",", ":"),
    )
    _ = fixture.write_text(safe_payload, encoding="utf-8")
    # When: the scanner inspects the JSON document.
    result = run_scanner(fixture)
    # Then: allowlisted synthetic and infrastructure values do not trigger findings.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "synthetic_boundary_findings=0" in result.stdout


def test_scanner_inspects_explicit_artifacts_root_but_skips_nested_cache_dirs(
    tmp_path: Path,
) -> None:
    # Given: an explicit artifacts/eval root with one real leak and one nested cache copy.
    eval_root = tmp_path / "artifacts" / "eval"
    eval_root.mkdir(parents=True)
    unsafe = eval_root / "report.json"
    unsafe_report = json.dumps(
        {
            "contact": "person@gmail.com",
            "subscriber": "010-1234-5678",
            "public_ip": "8.8.4.4",
            "token": "sk-proj-realisticsecretmaterial0000",
        },
        separators=(",", ":"),
    )
    _ = unsafe.write_text(unsafe_report, encoding="utf-8")
    nested_cache = eval_root / "node_modules"
    nested_cache.mkdir()
    cached_copy = nested_cache / "ignored.json"
    _ = cached_copy.write_text(
        '{"contact":"cache@gmail.com","subscriber":"010-0000-0000","public_ip":"1.1.1.1"}',
        encoding="utf-8",
    )
    # When: the explicit artifacts/eval root is scanned.
    result = run_scanner(eval_root)
    # Then: the declared root is authoritative, but nested dependency caches are still skipped.
    assert result.returncode == 1
    assert (
        "synthetic-boundary-finding:path=eval/report.json;kind=email;location=$.contact"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=eval/report.json;kind=msisdn;location=$.subscriber"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=eval/report.json;kind=ipv4;location=$.public_ip"
        in result.stdout
    )
    assert (
        "synthetic-boundary-finding:path=eval/report.json;kind=secret;location=$.token"
        in result.stdout
    )
    assert "ignored.json" not in result.stdout
    assert "cache@gmail.com" not in result.stdout
