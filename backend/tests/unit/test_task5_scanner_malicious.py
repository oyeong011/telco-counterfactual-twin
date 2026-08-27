"""Malicious AST fixtures for the no-execution scanner."""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER = REPO_ROOT / "scripts/assert_no_execution_surface.py"


def _scan_source(
    tmp_path: Path,
    source: str,
    *,
    directory: str = "domain",
) -> tuple[str, ...]:
    root = tmp_path / directory
    root.mkdir()
    path = root / "fixture.py"
    _ = path.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCANNER), str(path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return tuple(line for line in result.stdout.splitlines() if not line.startswith("mutation_"))


def test_scanner_rejects_private_mutation_callable(tmp_path: Path) -> None:
    # Given: mutation authority hidden behind a private function name.
    # When: the AST scanner inspects the source.
    findings = _scan_source(tmp_path, "def _execute_patch() -> None:\n    pass\n")
    # Then: private naming is not an authority bypass.
    assert any(item.endswith("python-callable:_execute_patch") for item in findings)


def test_scanner_rejects_named_mutation_lambda(tmp_path: Path) -> None:
    # Given: mutation authority assigned through a named lambda.
    findings = _scan_source(tmp_path, "execute_patch = lambda: None\n")
    # Then: assignment form is detected.
    assert any(":python-lambda:" in item for item in findings)


def test_scanner_rejects_dangerous_import_alias(tmp_path: Path) -> None:
    # Given: a dangerous OS function hidden behind a benign alias.
    findings = _scan_source(tmp_path, "from os import system as record_evidence\n")
    # Then: the imported capability origin is reported.
    assert any(":python-dangerous-import:" in item for item in findings)


def test_scanner_rejects_benign_name_calling_subprocess(tmp_path: Path) -> None:
    # Given: a benign callable name whose body starts a subprocess through an alias.
    source = (
        "import subprocess as transport\n"
        "def record_evidence() -> None:\n"
        "    transport.run(['echo', 'unsafe'], check=True)\n"
    )
    findings = _scan_source(tmp_path, source)
    # Then: behavior, not just identifiers, is scanned.
    assert any(":python-dangerous-call:" in item for item in findings)


def test_scanner_rejects_dangerous_callable_assignment_alias(tmp_path: Path) -> None:
    # Given: a dangerous callable copied into a benign variable before invocation.
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        "def record_evidence() -> None:\n"
        "    runner(['echo', 'unsafe'], check=True)\n"
    )
    findings = _scan_source(tmp_path, source)
    # Then: assignment aliasing cannot hide the execution capability.
    assert any(":python-dangerous-alias:" in item for item in findings)


def test_scanner_rejects_annotated_dangerous_callable_alias(tmp_path: Path) -> None:
    # Given: a dangerous callable copied through an annotated benign variable.
    source = (
        "import subprocess\n"
        "runner: callable = subprocess.run\n"
        "def record_evidence() -> None:\n"
        "    runner(['echo', 'unsafe'], check=True)\n"
    )
    findings = _scan_source(tmp_path, source)
    # Then: annotation syntax cannot hide the execution capability.
    assert any(":python-dangerous-alias:" in item for item in findings)


def test_scanner_rejects_dynamic_getattr_dispatch(tmp_path: Path) -> None:
    # Given: dynamic lookup of an OS process capability.
    source = "import os\nrunner = getattr(os, 'system')\nrunner('unsafe')\n"
    findings = _scan_source(tmp_path, source)
    # Then: dynamic dispatch is reported.
    assert any(":python-dynamic-call:" in item for item in findings)


def test_scanner_does_not_allow_arbitrary_bootstrap_named_path(tmp_path: Path) -> None:
    # Given: an unreviewed temporary directory named like the reviewed bootstrap adapter.
    findings = _scan_source(
        tmp_path,
        "def execute_patch() -> None:\n    pass\n",
        directory="bootstrap",
    )
    # Then: allowlisting is resolved by exact reviewed path, never a name-only part.
    assert findings


def test_scanner_allows_benign_simulation_and_data_lambdas(tmp_path: Path) -> None:
    # Given: simulator wording, a pure lambda, and non-executed prose.
    source = (
        "NOTE = 'never execute a network patch'\n"
        "metric_transform = lambda value: value + 1\n"
        "def run_simulation() -> None:\n"
        "    pass\n"
    )
    # When/Then: pure simulation surfaces remain clean.
    assert _scan_source(tmp_path, source) == ()
