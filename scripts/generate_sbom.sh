#!/usr/bin/env bash
set -euo pipefail

repo_root=""
out_path=""
check_mode="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      repo_root="$2"
      shift 2
      ;;
    --out)
      out_path="$2"
      shift 2
      ;;
    --check)
      check_mode="true"
      shift
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$repo_root" || -z "$out_path" ]]; then
  printf 'usage: %s --repo-root <path> --out <path>\n' "$0" >&2
  exit 1
fi

for tool_name in jq python3 shasum; do
  if ! command -v "$tool_name" >/dev/null 2>&1; then
    printf 'missing required tool: %s\n' "$tool_name" >&2
    exit 1
  fi
done

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  printf 'missing required tool: python3>=3.11\n' >&2
  exit 1
fi

readonly_repo_root="$(cd "$repo_root" && pwd)"
backend_lock="$readonly_repo_root/backend/uv.lock"
frontend_manifest="$readonly_repo_root/frontend/package.json"
frontend_lock="$readonly_repo_root/frontend/pnpm-lock.yaml"

for required_path in "$backend_lock" "$frontend_manifest" "$frontend_lock"; do
  if [[ ! -f "$required_path" ]]; then
    printf 'missing required lock source: %s\n' "${required_path#"$readonly_repo_root"/}" >&2
    exit 1
  fi
done

output_dir="$(dirname "$out_path")"
mkdir -p "$output_dir"
temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/task10-sbom.XXXXXX")"
temp_file="$temp_dir/payload.json"
canonical_file="$temp_dir/canonical.json"
trap 'rm -rf "$temp_dir"' EXIT

python3 - "$readonly_repo_root" "$backend_lock" "$frontend_manifest" "$frontend_lock" >"$temp_file" <<'PY'
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

repo_root = Path(sys.argv[1])
backend_lock = Path(sys.argv[2])
frontend_manifest = Path(sys.argv[3])
frontend_lock = Path(sys.argv[4])

PNPM_PACKAGE_PATTERN = re.compile(r"^\s{2}'?((?:@[^/]+/)?[^@]+)@([^']+)'?:\s*$")


def sha256_for(path: Path) -> str:
    result = subprocess.run(
        ["shasum", "-a", "256", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split()[0]


def load_python_components() -> list[dict[str, str]]:
    parsed = tomllib.loads(backend_lock.read_text(encoding="utf-8"))
    packages = parsed.get("package")
    if not isinstance(packages, list):
        raise SystemExit("backend/uv.lock does not contain package entries")
    components: list[dict[str, str]] = []
    for package in packages:
        if not isinstance(package, dict):
            raise SystemExit("backend/uv.lock package entry is not a table")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise SystemExit("backend/uv.lock package entry is missing name/version")
        components.append(
            {
                "ecosystem": "python",
                "name": name,
                "source": "backend/uv.lock",
                "version": version,
            }
        )
    return sorted(components, key=lambda item: (item["name"], item["version"]))


def load_node_components() -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    in_packages = False
    for line in frontend_lock.read_text(encoding="utf-8").splitlines():
        if line == "packages:":
            in_packages = True
            continue
        if not in_packages:
            continue
        if line and not line.startswith("  "):
            break
        matched = PNPM_PACKAGE_PATTERN.match(line)
        if matched is None:
            continue
        name, version = matched.groups()
        components.append(
            {
                "ecosystem": "node",
                "name": name,
                "source": "frontend/pnpm-lock.yaml",
                "version": version,
            }
        )
    if not components:
        raise SystemExit("frontend/pnpm-lock.yaml does not contain package entries")
    return sorted(components, key=lambda item: (item["name"], item["version"]))


def load_manifest_name() -> str:
    parsed = json.loads(frontend_manifest.read_text(encoding="utf-8"))
    name = parsed.get("name")
    if not isinstance(name, str) or not name:
        raise SystemExit("frontend/package.json is missing name")
    return name


artifacts = [
    {
        "path": "backend/uv.lock",
        "sha256": sha256_for(backend_lock),
    },
    {
        "path": "frontend/package.json",
        "sha256": sha256_for(frontend_manifest),
    },
    {
        "path": "frontend/pnpm-lock.yaml",
        "sha256": sha256_for(frontend_lock),
    },
]

payload = {
    "artifacts": artifacts,
    "components": load_python_components() + load_node_components(),
    "project": load_manifest_name(),
    "schema_version": "1.0",
    "notice": "Deterministic component inventory from pinned lock sources only; not a vulnerability scan.",
}

json.dump(payload, sys.stdout, sort_keys=True, separators=(",", ":"))
sys.stdout.write("\n")
PY

jq -S . "$temp_file" >"$canonical_file"
if [[ "$check_mode" == "true" ]]; then
  if [[ ! -f "$out_path" ]]; then
    printf 'sbom drift: missing tracked manifest %s\n' "$out_path" >&2
    exit 1
  fi
  if ! cmp -s "$canonical_file" "$out_path"; then
    printf 'sbom drift: %s is stale\n' "$out_path" >&2
    exit 1
  fi
  printf 'sbom_verified=%s\n' "${out_path}"
  exit 0
fi

mv "$canonical_file" "$out_path"
printf 'sbom_written=%s\n' "${out_path}"
