"""Malicious AST fixtures for the no-execution scanner."""

import subprocess
import sys
from pathlib import Path

import pytest

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
    findings = tuple(
        line for line in result.stdout.splitlines() if not line.startswith("mutation_")
    )
    assert result.returncode == int(bool(findings)), result.stdout + result.stderr
    return findings


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


def test_scanner_rejects_resolved_mutation_method_call(tmp_path: Path) -> None:
    # Given: a benign wrapper calling a mutation-shaped client method.
    source = "def record_evidence(client):\n    client.apply_patch()\n"
    # When: the resolved call target is scanned.
    findings = _scan_source(tmp_path, source)
    # Then: attribute qualification cannot hide the mutation capability.
    assert any(":python-mutation-call:" in item for item in findings)


@pytest.mark.parametrize(
    "builtin_name",
    ["eval", "exec", "compile", "__import__"],
)
def test_scanner_rejects_qualified_dangerous_builtin(
    tmp_path: Path,
    builtin_name: str,
) -> None:
    # Given: a dangerous builtin reached through its qualified module name.
    source = f"import builtins\ndef record_evidence():\n    builtins.{builtin_name}('1 + 1')\n"
    # When/Then: qualification cannot evade dangerous-call detection.
    assert _scan_source(tmp_path, source)


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nresult = list(map(subprocess.run, []))\n",
        "import subprocess\nresult = list(filter(subprocess.run, []))\n",
        "import functools\nimport subprocess\nrunner = functools.partial(subprocess.run)\n",
        (
            "import subprocess\n"
            "def register(handler):\n"
            "    return handler\n"
            "runner = register(subprocess.run)\n"
        ),
        "import subprocess\nrunners = [subprocess.run]\n",
        "import subprocess\nrunners = (subprocess.run,)\n",
        "import subprocess\nrunners = {'unsafe': subprocess.run}\n",
        "import subprocess\nrunners = {subprocess.run}\n",
    ],
)
def test_scanner_rejects_dangerous_callable_used_as_value(
    tmp_path: Path,
    source: str,
) -> None:
    # Given: process execution is passed or stored as a callable value.
    # When/Then: higher-order and container indirection remain capabilities.
    assert _scan_source(tmp_path, source)


def test_scanner_missing_explicit_root_fails_closed(tmp_path: Path) -> None:
    # Given: one explicitly requested root that does not exist.
    missing = tmp_path / "missing-domain"
    # When: the real CLI scans that root.
    result = subprocess.run(
        [sys.executable, str(SCANNER), str(missing)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    # Then: absent input cannot be misreported as a clean repository.
    assert result.returncode == 1
    assert "scan-root-error" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        (
            "import subprocess\n"
            "transport = subprocess\n"
            "def record_evidence():\n"
            "    transport.run(['echo', 'unsafe'], check=True)\n"
        ),
        (
            "import subprocess as process_module\n"
            "transport = process_module\n"
            "runner_module = transport\n"
            "runner_module.run(['echo', 'unsafe'], check=True)\n"
        ),
        ("import builtins\nruntime = builtins\nruntime.eval('1 + 1')\n"),
        ("import subprocess\ntransport: module = subprocess\ncallbacks = (transport.run,)\n"),
    ],
)
def test_scanner_rejects_transitive_module_assignment_aliases(
    tmp_path: Path,
    source: str,
) -> None:
    # Given/When/Then: ordinary and annotated module aliases retain their origin.
    assert _scan_source(tmp_path, source)


def test_scanner_benign_rebinding_clears_prior_module_alias(tmp_path: Path) -> None:
    # Given: a dangerous module alias statically rebound to a benign constructor result.
    source = (
        "import subprocess\ntransport = subprocess\ntransport = SafeTransport()\ntransport.run()\n"
    )
    # When/Then: the old alias does not create a false dangerous-call finding.
    assert _scan_source(tmp_path, source) == ()


def test_scanner_lambda_argument_shadows_module_alias(tmp_path: Path) -> None:
    source = "import subprocess\ninvoke = lambda subprocess: subprocess.run()\n"
    assert _scan_source(tmp_path, source) == ()


def test_scanner_nested_scope_inherits_alias_without_leaking_it(tmp_path: Path) -> None:
    # Given: one real closure capture and one unrelated name in a sibling scope.
    captured = (
        "def outer():\n"
        "    import subprocess\n"
        "    transport = subprocess\n"
        "    def inner():\n"
        "        transport.run(['echo', 'unsafe'], check=True)\n"
    )
    isolated = (
        "def configure():\n"
        "    import subprocess\n"
        "    transport = subprocess\n"
        "def record_evidence():\n"
        "    transport.run()\n"
    )
    # When/Then: lexical parents are visible, but completed sibling scopes are not.
    assert _scan_source(tmp_path, captured)
    assert _scan_source(tmp_path, isolated, directory="isolated") == ()


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nsubprocess = configure(subprocess.run)\n",
        ("import subprocess as runner\ndef runner(value=runner.run):\n    return value\n"),
        "import subprocess as runner\ninvoke = lambda value=runner.run: value()\n",
    ],
)
def test_scanner_resolves_dangerous_values_before_target_rebinding(
    tmp_path: Path,
    source: str,
) -> None:
    assert _scan_source(tmp_path, source)
