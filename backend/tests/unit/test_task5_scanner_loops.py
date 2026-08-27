"""Loop cardinality and exit-state regressions for the execution scanner."""

from pathlib import Path

import pytest

from .test_task5_scanner_malicious import scan_source


def _has_final_danger(findings: tuple[str, ...], line: int) -> bool:
    return any(f":{line}:python-dangerous-call:subprocess.run" in item for item in findings)


@pytest.mark.parametrize(
    "iterable",
    ["[]", "()", "set()", "{}", "range(0)", "range(3, 3)"],
)
def test_empty_loop_preserves_prior_dangerous_binding(
    tmp_path: Path,
    iterable: str,
) -> None:
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        f"for runner in {iterable}:\n"
        "    pass\n"
        "runner(['unsafe'])\n"
    )
    findings = scan_source(tmp_path, source)
    assert _has_final_danger(findings, 5)


def test_known_nonempty_loop_exposes_dangerous_last_element(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for runner in (subprocess.run,):\n"
        "    pass\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 5)


def test_known_nonempty_benign_loop_replaces_prior_danger(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        "for runner in (SafeRunner(),):\n"
        "    pass\n"
        "runner()\n"
    )
    assert not _has_final_danger(scan_source(tmp_path, source), 5)


def test_unknown_loop_merges_zero_iteration_prior_danger_with_benign_body(
    tmp_path: Path,
) -> None:
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        "for runner in providers:\n"
        "    runner = SafeRunner()\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 5)


def test_unknown_loop_merges_nonempty_danger_with_prior_benign_binding(
    tmp_path: Path,
) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for runner in providers:\n"
        "    runner = subprocess.run\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 5)


def test_break_path_is_not_overwritten_by_loop_else(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for runner in (SafeRunner(),):\n"
        "    runner = subprocess.run\n"
        "    break\n"
        "else:\n"
        "    runner = SafeRunner()\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 8)


@pytest.mark.parametrize("transfer", ["break", "continue"])
def test_transfer_stops_unreachable_benign_assignment_from_erasing_danger(
    tmp_path: Path,
    transfer: str,
) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for item in (1,):\n"
        "    runner = subprocess.run\n"
        f"    {transfer}\n"
        "    runner = SafeRunner()\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 7)


@pytest.mark.parametrize("transfer", ["break", "continue"])
def test_conditional_transfer_exit_merges_with_normal_body_exit(
    tmp_path: Path,
    transfer: str,
) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for item in (1,):\n"
        "    if condition:\n"
        "        runner = subprocess.run\n"
        f"        {transfer}\n"
        "    runner = SafeRunner()\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 8)


@pytest.mark.parametrize("control", ["", "    continue\n"])
def test_no_break_loop_else_can_sanitize_every_exit(
    tmp_path: Path,
    control: str,
) -> None:
    source = (
        "import subprocess\n"
        "runner = SafeRunner()\n"
        "for runner in providers:\n"
        "    runner = subprocess.run\n"
        f"{control}"
        "else:\n"
        "    runner = SafeRunner()\n"
        "runner()\n"
    )
    final_line = 8 if control else 7
    assert not _has_final_danger(scan_source(tmp_path, source), final_line)


def test_empty_outer_loop_does_not_apply_nested_loop_bindings(tmp_path: Path) -> None:
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        "for outer in []:\n"
        "    for runner in (SafeRunner(),):\n"
        "        pass\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 6)


def test_unknown_outer_loop_preserves_zero_path_across_nested_benign_loop(
    tmp_path: Path,
) -> None:
    source = (
        "import subprocess\n"
        "runner = subprocess.run\n"
        "for outer in providers:\n"
        "    for runner in (SafeRunner(),):\n"
        "        pass\n"
        "runner(['unsafe'])\n"
    )
    assert _has_final_danger(scan_source(tmp_path, source), 6)


def test_empty_loop_preserves_prior_benign_shadow_without_false_positive(
    tmp_path: Path,
) -> None:
    source = "runner = SafeRunner()\nfor runner in []:\n    pass\nrunner()\n"
    assert scan_source(tmp_path, source) == ()
