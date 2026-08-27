"""AST capability discovery for Python execution surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import final, override

from scripts.execution_surface_policy import (
    is_dangerous_call,
    is_mutation_name,
    resolved_expression,
)
from scripts.execution_surface_types import MutationSurface


@final
class _PythonSurfaceVisitor(ast.NodeVisitor):
    """Track qualified callables, aliases, and callable-valued capabilities."""

    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self._findings: set[MutationSurface] = set()
        self._aliases: dict[str, str] = {}

    @property
    def findings(self) -> tuple[MutationSurface, ...]:
        return tuple(sorted(self._findings))

    def _record(self, node: ast.AST, kind: str, name: str) -> None:
        self._findings.add(
            MutationSurface(str(self._path), getattr(node, "lineno", 0), kind, name)
        )

    def _resolved(self, expression: ast.expr) -> str | None:
        return resolved_expression(expression, self._aliases)

    def _record_reference(self, node: ast.expr) -> None:
        resolved = self._resolved(node)
        if resolved is None:
            return
        if is_dangerous_call(resolved):
            self._record(node, "python-dangerous-reference", resolved)
        elif is_mutation_name(resolved):
            self._record(node, "python-mutation-reference", resolved)

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if is_mutation_name(node.name):
            self._record(node, "python-callable", node.name)
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        for argument in arguments:
            if is_mutation_name(argument.arg):
                self._record(argument, "python-parameter", argument.arg)
        self.generic_visit(node)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for statement in node.body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and is_mutation_name(statement.target.id)
            ):
                self._record(statement, "python-field", statement.target.id)
        self.generic_visit(node)

    @override
    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            local = imported.asname or imported.name.split(".")[0]
            self._aliases[local] = imported.name

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for imported in node.names:
            origin = f"{module}.{imported.name}" if module else imported.name
            local = imported.asname or imported.name
            self._aliases[local] = origin
            if is_dangerous_call(origin):
                self._record(node, "python-dangerous-import", origin)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._resolved(node.func)
        if resolved == "getattr":
            self._record(node, "python-dynamic-call", resolved)
        elif resolved is not None:
            if is_dangerous_call(resolved):
                self._record(node, "python-dangerous-call", resolved)
            elif is_mutation_name(resolved):
                self._record(node, "python-mutation-call", resolved)
        self.generic_visit(node)

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_reference(node)

    @override
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_reference(node)
        self.generic_visit(node)

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        resolved = self._resolved(node.value)
        if resolved is not None and (
            is_dangerous_call(resolved) or is_mutation_name(resolved)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._aliases[target.id] = resolved
                    self._record(target, "python-dangerous-alias", resolved)
        if isinstance(node.value, ast.Lambda):
            for target in node.targets:
                if isinstance(target, ast.Name) and is_mutation_name(target.id):
                    self._record(node, "python-lambda", target.id)
        self.generic_visit(node)

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and isinstance(node.target, ast.Name):
            resolved = self._resolved(node.value)
            if resolved is not None and (
                is_dangerous_call(resolved) or is_mutation_name(resolved)
            ):
                self._aliases[node.target.id] = resolved
                self._record(node.target, "python-dangerous-alias", resolved)
            if isinstance(node.value, ast.Lambda) and is_mutation_name(node.target.id):
                self._record(node, "python-lambda", node.target.id)
        self.generic_visit(node)


def python_findings(path: Path) -> tuple[MutationSurface, ...]:
    """Parse one Python file and return every capability finding."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as error:
        return (
            MutationSurface(str(path), 0, "python-parse-error", type(error).__name__),
        )
    visitor = _PythonSurfaceVisitor(path)
    visitor.visit(tree)
    return visitor.findings
