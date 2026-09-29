"""Task 10 CI and Makefile contract tests."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
CI_WORKFLOW: Final = REPO_ROOT / ".github/workflows/ci.yml"
RELEASE_WORKFLOW: Final = REPO_ROOT / ".github/workflows/release-candidate.yml"
MAKEFILE: Final = REPO_ROOT / "Makefile"
ENV_EXAMPLE: Final = REPO_ROOT / ".env.example"
PINNED_UPLOAD_ARTIFACT_SHA: Final = "ea165f8d65b6e75b540449e92b4886f43607fa02"
USES_PATTERN: Final = re.compile(r"^\s*uses:\s*([^@\s]+)@([0-9A-Za-z._-]+)\s*$")
FULL_SHA_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED_VERIFY_DEPS: Final = (
    "check-specs",
    "python-lint",
    "python-typecheck",
    "python-test",
    "frontend-check",
    "frontend-typecheck",
    "frontend-test",
    "frontend-build",
    "contracts-check",
    "release-evidence-check",
)
NONSECRET_UPLOAD_PATHS: Final = (
    "artifacts/contracts/openapi.json",
    "artifacts/contracts/mcp-tools.json",
    "artifacts/eval/*.json",
    "artifacts/eval/*.jsonl",
    "artifacts/eval-v2/*.json",
    "artifacts/release/evidence-manifest.json",
    "artifacts/security/*.json",
    "frontend/public/build-info.json",
)


def workflow_uses(workflow: Path) -> tuple[tuple[str, str], ...]:
    """Return every GitHub action reference used by one workflow."""
    references: list[tuple[str, str]] = []
    for line in workflow.read_text(encoding="utf-8").splitlines():
        match = USES_PATTERN.match(line)
        if match is not None:
            references.append((match.group(1), match.group(2)))
    return tuple(references)


def target_body(makefile: str, target: str) -> str:
    """Return the command body for one Make target."""
    pattern = re.compile(rf"^{re.escape(target)}:(?:.*\n)(?:\t.*\n)*", re.MULTILINE)
    match = pattern.search(makefile)
    assert match is not None
    return match.group(0)


def assert_pinned_actions(workflow: Path) -> None:
    for action, ref in workflow_uses(workflow):
        assert FULL_SHA_PATTERN.fullmatch(ref), f"{workflow.name}:{action}@{ref}"


def assert_step_order(workflow: str, targets: tuple[str, ...]) -> None:
    indexes = tuple(workflow.index(f"run: make {target}") for target in targets)
    assert indexes == tuple(sorted(indexes))


def test_ci_workflow_is_pinned_full_history_and_nonsecret_artifact_only() -> None:
    # Given: the Task 10 CI workflow.
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    # When/Then: it uses least-privilege permissions and immutable action refs.
    assert "permissions:\n  contents: read" in workflow
    assert "fetch-depth: 0" in workflow
    assert "concurrency:" in workflow
    assert "timeout-minutes:" in workflow
    assert_pinned_actions(CI_WORKFLOW)
    assert f"actions/upload-artifact@{PINNED_UPLOAD_ARTIFACT_SHA}" in workflow
    for path in NONSECRET_UPLOAD_PATHS:
        assert path in workflow
    assert ".env" not in workflow
    assert "if: always()\n        uses: actions/upload-artifact" not in workflow


def test_ci_workflow_invokes_shared_targets_without_swallowing_steps() -> None:
    # Given: both Task 10 workflows.
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    # When/Then: each target is its own step, so failures are attributed directly.
    for workflow in (ci, release):
        for target in ("bootstrap", "verify", "security", "probe", "generate-release-evidence"):
            assert f"run: make {target}" in workflow
        assert "run: make bootstrap verify" not in workflow
        assert "if: always()" in workflow
        assert_step_order(
            workflow,
            ("bootstrap", "verify", "security", "probe", "generate-release-evidence"),
        )


def test_release_candidate_is_task10_proof_only() -> None:
    # Given: the manually dispatched release-candidate proof workflow.
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    # When/Then: it verifies and uploads evidence without deployment or release behavior.
    assert "workflow_dispatch:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes:" in workflow
    assert_pinned_actions(RELEASE_WORKFLOW)
    assert f"actions/upload-artifact@{PINNED_UPLOAD_ARTIFACT_SHA}" in workflow
    forbidden = ("gh release", "cloudflare", "pages deploy", "vercel", "wif", "id-token: write")
    assert not any(term in workflow.lower() for term in forbidden)


def test_makefile_targets_encode_task10_contracts() -> None:
    # Given: the shared Makefile used by both workflows.
    makefile = MAKEFILE.read_text(encoding="utf-8")

    # When/Then: bootstrap, verify, security, contract, evidence, and probe targets are wired.
    bootstrap = target_body(makefile, "bootstrap")
    assert "uv sync --project backend --locked --all-groups" in bootstrap
    assert "pnpm --dir frontend install --frozen-lockfile" in bootstrap
    verify_header = target_body(makefile, "verify").splitlines()[0]
    for dependency in REQUIRED_VERIFY_DEPS:
        assert dependency in verify_header
    contracts = target_body(makefile, "contracts-check")
    assert "scripts/export_mcp_tools.py --check" in contracts
    assert "export_mcp_contract.py" not in contracts
    security = target_body(makefile, "security")
    assert "scripts/assert_no_execution_surface.py" in security
    assert "scripts/scan_synthetic_boundary.py" in security
    assert "sbom-check" in target_body(makefile, "security").splitlines()[0]
    sbom_generate = target_body(makefile, "sbom-generate")
    assert (
        "scripts/generate_sbom.sh --repo-root . --out artifacts/security/component-inventory.json"
    ) in sbom_generate
    sbom_check = target_body(makefile, "sbom-check")
    assert "scripts/generate_sbom.sh --repo-root . --out" in sbom_check
    assert "cmp" in sbom_check
    evidence = target_body(makefile, "generate-release-evidence")
    assert "scripts/generate_release_evidence.py" in evidence
    assert "scripts/verify_release_manifest.py" in evidence
    probe = target_body(makefile, "probe")
    assert "scripts/with_compose_cleanup.sh -f docker-compose.yml --" in probe
    assert "scripts/probe_stack.py --out artifacts/probe/local-stack-probe.json" in probe


def test_env_example_contains_only_synthetic_local_defaults() -> None:
    # Given: the checked-in environment example.
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    # When/Then: it contains local synthetic defaults and no credential-shaped values.
    assert "TWIN_ENVIRONMENT=local" in env_example
    assert "VITE_API_BASE_URL=http://127.0.0.1:18080" in env_example
    forbidden = ("API_KEY=", "TOKEN=", "PASSWORD=", "PRIVATE_KEY=", "SECRET=")
    assert not any(marker in env_example for marker in forbidden)
