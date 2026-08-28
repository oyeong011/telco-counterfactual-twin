"""Independent fixtures for Task 9 frontend build-identity tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Final

import rfc8785
from pydantic import JsonValue, TypeAdapter

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
BUILD_SCRIPT: Final = REPO_ROOT / "scripts/generate_frontend_build_info.py"
JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
ASSET_MANIFEST: Final = Path(".vite/manifest.json")
TRUST_DESCRIPTOR: Final = Path("specs/schemas/visual-qa-reviewers-trust")
SHARED_NODE_MODULES: Final = REPO_ROOT / "frontend/node_modules"


def json_object(raw: bytes) -> dict[str, JsonValue]:
    """Parse a JSON object without relying on the implementation under test."""
    payload = JSON_ADAPTER.validate_json(raw)
    assert isinstance(payload, dict)
    return payload


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one real CLI boundary and capture its observable result."""
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


def write_stale_vite_dist(root: Path) -> Path:
    """Write a forged ignored output tree that must never define identity."""
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
    """Copy source into clean Git with dependencies but no ignored build output."""
    root = tmp_path / "repo"
    _ = shutil.copytree(
        REPO_ROOT,
        root,
        ignore=shutil.ignore_patterns(".git", ".venv", "node_modules", "dist", "__pycache__"),
    )
    _ = run(["git", "init", "-q"], root)
    exclude = root / ".git/info/exclude"
    _ = exclude.write_text(
        exclude.read_text(encoding="utf-8") + "\nfrontend/node_modules\n",
        encoding="utf-8",
    )
    _ = run(["git", "config", "user.email", "task9@example.invalid"], root)
    _ = run(["git", "config", "user.name", "Task9"], root)
    descriptor = root / TRUST_DESCRIPTOR
    descriptor.parent.mkdir(parents=True, exist_ok=True)
    _ = descriptor.write_text(
        json.dumps(
            {
                "reviewers": [
                    {
                        "key_id": "visual-review-root-v1",
                        "public_key": "zlYCzcL_WIkT3sEYc15zM39s_TP1zlmQqJSSZjarlzM",
                        "role": "visual-fidelity",
                    },
                    {
                        "key_id": "accessibility-review-root-v1",
                        "public_key": "QnLIVBBl7D_x2E8fX7z-OU6JyUc2Y8o3bfabn61rFoI",
                        "role": "accessibility",
                    },
                ],
                "schema_version": "1.0",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    assert run(["git", "add", "."], root).returncode == 0
    assert run(["git", "commit", "-qm", "fixture"], root).returncode == 0
    (root / "frontend/node_modules").symlink_to(SHARED_NODE_MODULES, target_is_directory=True)
    return root


def copy_history_repo(tmp_path: Path) -> Path:
    """Clone real branch history without ignored dependencies or build output."""
    root = tmp_path / "history-repo"
    result = run(
        ["git", "clone", "--local", "--no-hardlinks", str(REPO_ROOT), str(root)],
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
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
        root / "frontend/pnpm-workspace.yaml",
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


def canonical_json_file_hash(path: Path) -> str:
    """Hash one parsed JSON descriptor independently with RFC8785 plus newline."""
    value = JSON_ADAPTER.validate_json(path.read_bytes())
    return hashlib.sha256(rfc8785.dumps(value) + b"\n").hexdigest()
