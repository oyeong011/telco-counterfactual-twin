"""Independent fixtures for Task 9 frontend build-identity tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

from pydantic import JsonValue, TypeAdapter

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
BUILD_SCRIPT: Final = REPO_ROOT / "scripts/generate_frontend_build_info.py"
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
ASSET_MANIFEST: Final = Path(".vite/manifest.json")


def json_object(raw: bytes) -> dict[str, JsonValue]:
    """Parse a JSON object without relying on the implementation under test."""
    payload = JSON_ADAPTER.validate_json(raw)
    assert isinstance(payload, dict)
    return payload


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one real CLI boundary and capture its observable result."""
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def write_vite_dist(root: Path) -> Path:
    """Write a small complete Vite-style output tree with a real manifest."""
    dist = root / "frontend/dist"
    assets = dist / "assets"
    manifest = dist / ASSET_MANIFEST
    assets.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    _ = (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/main.js"></script>\n',
        encoding="utf-8",
    )
    _ = (assets / "main.js").write_text("console.log('twin')\n", encoding="utf-8")
    _ = (assets / "main.css").write_text(":root{color:#21151f}\n", encoding="utf-8")
    payload = {
        "index.html": {
            "file": "assets/main.js",
            "isEntry": True,
            "css": ["assets/main.css"],
        }
    }
    _ = manifest.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return dist


def copy_repo(tmp_path: Path) -> Path:
    """Copy the source into a clean local Git repository and emit Vite assets."""
    root = tmp_path / "repo"
    _ = shutil.copytree(
        REPO_ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "dist", "__pycache__"),
    )
    _ = run(["git", "init", "-q"], root)
    _ = run(["git", "config", "user.email", "task9@example.invalid"], root)
    _ = run(["git", "config", "user.name", "Task9"], root)
    assert run(["git", "add", "."], root).returncode == 0
    assert run(["git", "commit", "-qm", "fixture"], root).returncode == 0
    _ = write_vite_dist(root)
    return root


def records_hash(root: Path, files: tuple[Path, ...]) -> str:
    """Compute the plan's canonical sorted path/NUL/SHA-256 record hash."""
    records = b"".join(
        path.relative_to(root).as_posix().encode()
        + b"\0"
        + hashlib.sha256(path.read_bytes()).hexdigest().encode()
        + b"\n"
        for path in sorted(files, key=lambda item: item.relative_to(root).as_posix())
    )
    return hashlib.sha256(records).hexdigest()


def canonical_runtime_hash(root: Path) -> str:
    """Compute the exact Twin UI path set declared by the accepted plan."""
    files = (
        *(path for path in (root / "frontend/src").rglob("*") if path.is_file()),
        root / "frontend/package.json",
        root / "frontend/pnpm-lock.yaml",
        *(path for path in (root / "frontend").glob("tsconfig*.json") if path.is_file()),
        *(path for path in (root / "specs/schemas").rglob("*") if path.is_file()),
    )
    return records_hash(root, tuple(files))


def emitted_asset_hash(root: Path) -> str:
    """Compute emitted-asset records relative to the Vite output root."""
    dist = root / "frontend/dist"
    excluded = {dist / "build-info.json", dist / ASSET_MANIFEST}
    files = tuple(path for path in dist.rglob("*") if path.is_file() and path not in excluded)
    return records_hash(dist, files)
