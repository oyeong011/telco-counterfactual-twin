"""AST/schema no-execution scanner behavior tests."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER = REPO_ROOT / "scripts/assert_no_execution_surface.py"


def _scan(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), *(str(path) for path in paths)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_repository_product_contracts_have_zero_mutation_surfaces() -> None:
    # Given: the exported schemas and complete backend source tree.
    # When: the structural scanner inspects both roots.
    result = _scan(REPO_ROOT / "specs/schemas", REPO_ROOT / "backend/src")
    # Then: provisioning internals and benign lexemes do not cause false positives.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "mutation_surfaces=0" in result.stdout


def test_scanner_rejects_public_mutation_callable_and_schema_callback(tmp_path: Path) -> None:
    # Given: one mutation-shaped public callable and one dynamic callback property.
    source = tmp_path / "unsafe.py"
    _ = source.write_text("def execute_patch() -> None:\n    pass\n", encoding="utf-8")
    schema = tmp_path / "unsafe.schema.json"
    _ = schema.write_text(
        '{"type":"object","properties":{"callback":{"type":"string"}}}',
        encoding="utf-8",
    )
    # When: both boundary artifacts are scanned.
    result = _scan(source, schema)
    # Then: both exact structural locations are reported and exit is nonzero.
    assert result.returncode == 1
    assert "execute_patch" in result.stdout
    assert "callback" in result.stdout


def test_scanner_ignores_benign_words_and_non_surface_string_literals(tmp_path: Path) -> None:
    # Given: benign identifiers plus documentation-only prohibited words.
    source = tmp_path / "benign.py"
    _ = source.write_text(
        'executioner_state = "idle"\ncommandment_count = 10\nNOTE = "never execute or revoke"\n',
        encoding="utf-8",
    )
    # When: the AST is scanned rather than naively grepped.
    result = _scan(source)
    # Then: no false surface is reported.
    assert result.returncode == 0
    assert "mutation_surfaces=0" in result.stdout
