# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["anyio>=4,<5", "pydantic==2.13.4", "pynacl>=1.6.2,<2"]
# ///
# ─── How to run ───
# uv run --project backend python -m scripts.task5_safety_probe --out /tmp/task5-probe.json
"""Write one self-hashed Task5 evidence artifact."""

from __future__ import annotations

import sys
from pathlib import Path

import anyio

from scripts.task5_probe_flow import run_probe
from scripts.task5_probe_provenance import REPOSITORY_ROOT, ProbeArtifactWorktreeError
from scripts.task5_probe_support import ProbeUsageError


def main(arguments: list[str]) -> int:
    """Write complete evidence and disclose only its self-hash."""
    if len(arguments) != 2 or arguments[0] != "--out":
        raise ProbeUsageError
    output = Path(arguments[1]).resolve()
    if output.is_relative_to(REPOSITORY_ROOT):
        print("artifact-output-inside-repository", file=sys.stderr)
        return 1
    try:
        artifact = anyio.run(run_probe)
    except ProbeArtifactWorktreeError as error:
        print(str(error), file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    _ = output.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    print(f"task5-probe-pass artifact_hash={artifact.artifact_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
