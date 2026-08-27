"""Container-provenance regressions for the execution-surface scanner."""

from pathlib import Path

import pytest

from .test_task5_scanner_malicious import scan_source


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\nmodules = [subprocess]\nmodules[0].run(['unsafe'])\n",
        "import subprocess\nmodules = (subprocess,)\nmodules[0].run(['unsafe'])\n",
        (
            "import subprocess\n"
            "modules = {'transport': subprocess}\n"
            "modules['transport'].run(['unsafe'])\n"
        ),
        (
            "import subprocess\n"
            "catalog = {'groups': [[subprocess]]}\n"
            "catalog['groups'][0][0].run(['unsafe'])\n"
        ),
        ("import subprocess\naliases = modules = [subprocess]\naliases[0].run(['unsafe'])\n"),
    ],
)
def test_scanner_resolves_module_provenance_through_static_containers(
    tmp_path: Path,
    source: str,
) -> None:
    findings = scan_source(tmp_path, source)
    assert any(":python-dangerous-call:subprocess.run" in item for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        (
            "import subprocess\n"
            "modules = [SafeTransport(), subprocess]\n"
            "modules[index].run(['unsafe'])\n"
        ),
        (
            "import subprocess\n"
            "modules = {'safe': SafeTransport(), 'shell': subprocess}\n"
            "modules[key].run(['unsafe'])\n"
        ),
    ],
)
def test_scanner_fails_closed_for_dynamic_selection_from_dangerous_container(
    tmp_path: Path,
    source: str,
) -> None:
    findings = scan_source(tmp_path, source)
    assert any(":python-dangerous-call:subprocess.run" in item for item in findings)


def test_scanner_preserves_callable_provenance_when_read_from_container(
    tmp_path: Path,
) -> None:
    source = "import subprocess\ncallbacks = [subprocess.run]\ncallbacks[0](['unsafe'])\n"
    findings = scan_source(tmp_path, source)
    assert any(":3:python-dangerous-call:subprocess.run" in item for item in findings)


def test_scanner_preserves_container_callback_passed_to_higher_order_call(
    tmp_path: Path,
) -> None:
    source = "import subprocess\ncallbacks = [subprocess.run]\nregister(callbacks[0])\n"
    findings = scan_source(tmp_path, source)
    assert any(":3:python-dangerous-reference:subprocess.run" in item for item in findings)


def test_scanner_fails_closed_before_dynamic_nested_selection_loses_shape(
    tmp_path: Path,
) -> None:
    source = "import subprocess\ncatalog = [[subprocess]]\ncatalog[index][0].run(['unsafe'])\n"
    findings = scan_source(tmp_path, source)
    assert any(":python-dangerous-container:subprocess" in item for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        (
            "import subprocess\n"
            "modules = (subprocess,)\n"
            "for module in modules:\n"
            "    module.run(['unsafe'])\n"
        ),
        ("import subprocess\nfor module in {subprocess}:\n    module.run(['unsafe'])\n"),
        (
            "import subprocess\n"
            "modules = ((subprocess,),)\n"
            "(selected,) = modules[0]\n"
            "selected.run(['unsafe'])\n"
        ),
        (
            "import subprocess\n"
            "modules = ((subprocess,),)\n"
            "for (selected,) in modules:\n"
            "    selected.run(['unsafe'])\n"
        ),
    ],
)
def test_scanner_resolves_clear_static_iteration_and_destructuring(
    tmp_path: Path,
    source: str,
) -> None:
    findings = scan_source(tmp_path, source)
    assert any(":python-dangerous-call:subprocess.run" in item for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        ("import subprocess\nmodules = [SafeTransport(), subprocess]\nmodules[0].run()\n"),
        (
            "import subprocess\n"
            "modules = [subprocess]\n"
            "modules = [SafeTransport()]\n"
            "modules[0].run()\n"
        ),
        "modules = [SafeTransport(), SafeTransport()]\nmodules[index].run()\n",
    ],
)
def test_scanner_does_not_retain_danger_after_proven_benign_selection_or_shadow(
    tmp_path: Path,
    source: str,
) -> None:
    assert scan_source(tmp_path, source) == ()
