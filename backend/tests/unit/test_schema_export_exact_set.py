from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

from .contract_cases import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path


def test_schema_check_rejects_obsolete_extra_snapshot(tmp_path: Path) -> None:
    out_dir = tmp_path / "schemas"
    export = subprocess.run(
        (
            sys.executable,
            str(REPO_ROOT / "scripts/export_schemas.py"),
            "--out-dir",
            str(out_dir),
        ),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert export.returncode == 0
    _ = (out_dir / "obsolete.schema.json").write_text("{}\n", encoding="utf-8")

    check = subprocess.run(
        (
            sys.executable,
            str(REPO_ROOT / "scripts/export_schemas.py"),
            "--check",
            "--out-dir",
            str(out_dir),
        ),
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert check.returncode == 3
    assert check.stderr == "contract-schema-extra:obsolete\n"
