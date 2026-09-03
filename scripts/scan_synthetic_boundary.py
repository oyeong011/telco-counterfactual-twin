#!/usr/bin/env -S uv run --project backend python
"""Reject real-looking personal identifiers in declared source roots."""

from __future__ import annotations

import argparse
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeGuard

from pydantic import JsonValue, TypeAdapter, ValidationError

TEXT_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsonl",
        ".md",
        ".mjs",
        ".cjs",
        ".py",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
SKIP_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "artifacts",
        "build",
        "coverage",
        "dist",
        "node_modules",
    }
)
MAX_FILE_BYTES: Final = 1_000_000
EMAIL_PATTERN: Final = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
MSISDN_PATTERN: Final = re.compile(
    r"(?<!\d)(?:\+?82(?:10|11|16|17|18|19)|010)[- ]?\d{3,4}[- ]?\d{4}(?!\d)"
)
IMSI_PATTERN: Final = re.compile(
    r"(?<![0-9a-f])(?:450|310|311|262)\d{12}(?![0-9a-f])", re.IGNORECASE
)
IPV4_PATTERN: Final = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"sk-(?:proj|live|test)-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
)
PEM_PRIVATE_KEY_PATTERN: Final = re.compile(
    r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----\s+"
    + r"[A-Za-z0-9+/=\s]+\s+"
    + r"-----END (?:[A-Z ]+ )?PRIVATE KEY-----"
)
IPV4_VERSION: Final = 4
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
STRING_LIST_ADAPTER: Final[TypeAdapter[list[str]]] = TypeAdapter(list[str])


@dataclass(frozen=True, slots=True)
class Finding:
    """One redacted synthetic-boundary hit."""

    path: str
    kind: str
    location: str

    def render(self) -> str:
        """Return the stable scanner output line."""
        return (
            "synthetic-boundary-finding:"
            f"path={self.path};kind={self.kind};location={self.location}"
        )


def _allowed_email(value: str) -> bool:
    _, _, domain = value.partition("@")
    normalized = domain.lower()
    return normalized in {
        "example.com",
        "example.invalid",
        "example.org",
        "localhost",
    } or (normalized.endswith(".gserviceaccount.com"))


def _public_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return bool(address.version == IPV4_VERSION and address.is_global)


def _find_kinds(value: str) -> tuple[str, ...]:
    kinds: list[str] = []
    if EMAIL_PATTERN.search(value) and any(
        not _allowed_email(match.group(0)) for match in EMAIL_PATTERN.finditer(value)
    ):
        kinds.append("email")
    if MSISDN_PATTERN.search(value):
        kinds.append("msisdn")
    if IMSI_PATTERN.search(value):
        kinds.append("imsi")
    if any(_public_ipv4(match.group(0)) for match in IPV4_PATTERN.finditer(value)):
        kinds.append("ipv4")
    if any(pattern.search(value) for pattern in SECRET_PATTERNS):
        kinds.append("secret")
    return tuple(kinds)


def _json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace(".", "\\.")


def _scan_json(
    value: JsonValue, *, findings: list[Finding], path: str, location: str
) -> None:
    if isinstance(value, str):
        findings.extend(
            Finding(path=path, kind=kind, location=location)
            for kind in _find_kinds(value)
        )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json(
                item, findings=findings, path=path, location=f"{location}[{index}]"
            )
        return
    if isinstance(value, dict):
        for key in sorted(value):
            _scan_json(
                value[key],
                findings=findings,
                path=path,
                location=f"{location}.{_json_pointer_token(key)}",
            )


def _scan_lines(text: str, *, findings: list[Finding], path: str) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        findings.extend(
            Finding(path=path, kind=kind, location=f"line:{line_number}")
            for kind in _find_kinds(line)
        )


def _scan_jsonl(text: str, *, findings: list[Finding], path: str) -> None:
    for index, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = JSON_VALUE_ADAPTER.validate_json(stripped)
        except ValueError:
            _scan_lines(stripped, findings=findings, path=path)
        else:
            _scan_json(parsed, findings=findings, path=path, location=f"$[{index}]")


def _append_multiline_secret(text: str, *, findings: list[Finding], path: str) -> None:
    matched_private_key = PEM_PRIVATE_KEY_PATTERN.search(text)
    if matched_private_key is None:
        return
    line_number = text[: matched_private_key.start()].count("\n") + 1
    findings.append(Finding(path=path, kind="secret", location=f"line:{line_number}"))


def _scan_text(path: Path, display_path: str) -> list[Finding]:
    if path.stat().st_size > MAX_FILE_BYTES:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[Finding] = []
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            parsed = JSON_VALUE_ADAPTER.validate_json(text)
        except ValueError:
            _scan_lines(text, findings=findings, path=display_path)
        else:
            _scan_json(parsed, findings=findings, path=display_path, location="$")
        return findings
    if suffix == ".jsonl":
        _scan_jsonl(text, findings=findings, path=display_path)
        return findings
    _scan_lines(text, findings=findings, path=display_path)
    _append_multiline_secret(text, findings=findings, path=display_path)
    return findings


def _skip_nested_path(root: Path, path: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    return any(part in SKIP_DIR_NAMES for part in relative_parts[:-1])


def _iter_paths(root: Path) -> list[tuple[Path, str]]:
    base = root.parent
    if root.is_file():
        return [(root, root.relative_to(base).as_posix())]
    collected: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if _skip_nested_path(root, path):
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        collected.append((path, path.relative_to(base).as_posix()))
    return collected


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    try:
        _ = STRING_LIST_ADAPTER.validate_python(value)
    except ValidationError:
        return False
    return True


def _parse_roots(argv: Sequence[str] | None = None) -> tuple[Path, ...]:
    """Parse CLI roots and return a typed tuple for scanning."""
    parser = argparse.ArgumentParser(
        description="Reject real-looking personal identifiers from declared source roots."
    )
    _ = parser.add_argument("roots", nargs="+")
    namespace = parser.parse_args(argv)
    raw_roots = namespace.__dict__.get("roots")
    if not _is_string_list(raw_roots):
        raise ValueError("roots-must-be-string-list")
    return tuple(Path(item) for item in raw_roots)


def main(argv: Sequence[str] | None = None) -> int:
    """Scan explicit roots and exit nonzero on any redacted finding."""
    roots = _parse_roots(argv)
    findings: list[Finding] = []
    for root in roots:
        for path, display_path in _iter_paths(root):
            findings.extend(_scan_text(path, display_path))

    rendered = sorted({finding.render() for finding in findings})
    for line in rendered:
        print(line)
    print(f"synthetic_boundary_findings={len(rendered)}")
    return int(bool(rendered))


if __name__ == "__main__":
    raise SystemExit(main())
