# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# ─── How to run ───
# uv run --project backend python scripts/assert_no_execution_surface.py specs/schemas backend/src
"""Reject mutation-shaped public Python and JSON-schema surfaces."""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, assert_never, final, override

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

JSON_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
CAMEL_BOUNDARY: Final = re.compile(r"([a-z0-9])([A-Z])")
SEPARATOR: Final = re.compile(r"[^A-Za-z0-9]+")
DIRECT_TOKENS: Final = frozenset(
    {"callback", "command", "execute", "execution", "revoke", "revocation", "shell"}
)
MUTATION_VERBS: Final = frozenset({"apply", "commit", "execute", "push", "revoke"})
EXCLUDED_DIRECTORY_NAMES: Final = frozenset({".venv", "__pycache__", "bootstrap"})


class _JsonEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    value: JsonValue


@dataclass(frozen=True, slots=True, order=True)
class MutationSurface:
    """One exact structural mutation-authority finding."""

    path: str
    line: int
    kind: str
    name: str


def _tokens(name: str) -> frozenset[str]:
    expanded = CAMEL_BOUNDARY.sub(r"\1_\2", name)
    return frozenset(item.lower() for item in SEPARATOR.split(expanded) if item)


def _is_mutation_name(name: str) -> bool:
    tokens = _tokens(name)
    if tokens & DIRECT_TOKENS:
        return True
    return bool(tokens & MUTATION_VERBS) and bool(
        tokens & {"approval", "config", "network", "operation", "patch", "payload"}
    )


@final
class _PythonSurfaceVisitor(ast.NodeVisitor):
    """Inspect callable names, parameters, and class boundary fields only."""

    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self.findings: list[MutationSurface] = []

    def _record(self, node: ast.AST, kind: str, name: str) -> None:
        self.findings.append(
            MutationSurface(str(self._path), getattr(node, "lineno", 0), kind, name)
        )

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not node.name.startswith("_") and _is_mutation_name(node.name):
            self._record(node, "python-callable", node.name)
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        for argument in arguments:
            if _is_mutation_name(argument.arg):
                self._record(argument, "python-parameter", argument.arg)
        self.generic_visit(node)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Inspect one synchronous callable surface."""
        self._visit_callable(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Inspect one asynchronous callable surface."""
        self._visit_callable(node)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Inspect annotated class fields without grepping implementation strings."""
        for statement in node.body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and _is_mutation_name(statement.target.id)
            ):
                self._record(statement, "python-field", statement.target.id)
        self.generic_visit(node)


def _excluded(path: Path) -> bool:
    return bool(set(path.parts) & EXCLUDED_DIRECTORY_NAMES)


def _python_findings(path: Path) -> tuple[MutationSurface, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as error:
        return (
            MutationSurface(str(path), 0, "python-parse-error", type(error).__name__),
        )
    visitor = _PythonSurfaceVisitor(path)
    visitor.visit(tree)
    return tuple(visitor.findings)


def _schema_fields(value: JsonValue) -> Iterable[str]:
    envelope = _JsonEnvelope(value=value)
    match envelope.value:
        case dict() as mapping:
            properties = mapping.get("properties")
            if isinstance(properties, dict):
                yield from properties
            for nested in mapping.values():
                yield from _schema_fields(nested)
        case list() as items:
            for item in items:
                yield from _schema_fields(item)
        case None:
            return
        case str() | bool() | int() | float():
            return
        case _:
            assert_never(envelope.value)


def _schema_findings(path: Path) -> tuple[MutationSurface, ...]:
    try:
        value = JSON_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        return (
            MutationSurface(str(path), 0, "schema-parse-error", type(error).__name__),
        )
    return tuple(
        MutationSurface(str(path), 0, "schema-field", name)
        for name in _schema_fields(value)
        if _is_mutation_name(name)
    )


def _files(paths: Sequence[Path]) -> tuple[Path, ...]:
    discovered: set[Path] = set()
    for path in paths:
        if path.is_dir():
            discovered.update(
                candidate
                for candidate in path.rglob("*.py")
                if not _excluded(candidate)
            )
            discovered.update(
                candidate
                for candidate in path.rglob("*.json")
                if not _excluded(candidate)
            )
        elif path.suffix in {".py", ".json"} and not _excluded(path):
            discovered.add(path)
    return tuple(sorted(discovered))


def scan_paths(paths: Sequence[Path]) -> tuple[MutationSurface, ...]:
    """Return sorted structural findings from explicit source/schema roots."""
    findings: list[MutationSurface] = []
    for path in _files(paths):
        if path.suffix == ".py":
            findings.extend(_python_findings(path))
        else:
            findings.extend(_schema_findings(path))
    return tuple(sorted(findings))


def main(arguments: Sequence[str]) -> int:
    """Print stable scanner evidence and return nonzero on any mutation surface."""
    if not arguments:
        print("usage: assert_no_execution_surface.py PATH [PATH ...]", file=sys.stderr)
        return 2
    findings = scan_paths(tuple(Path(argument) for argument in arguments))
    for finding in findings:
        print(f"{finding.path}:{finding.line}:{finding.kind}:{finding.name}")
    print(f"mutation_surfaces={len(findings)}")
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
