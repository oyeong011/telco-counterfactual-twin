"""AST capability discovery for Python execution surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final, Literal, final, override

from scripts.execution_surface_policy import (
    is_dangerous_call,
    is_mutation_name,
    resolved_expression,
)
from scripts.execution_surface_types import MutationSurface

type _ScopeKind = Literal["global", "function", "class"]
SHADOWED_NAME: Final = "<shadowed>"


@final
class _PythonSurfaceVisitor(ast.NodeVisitor):
    """Track qualified callables, aliases, and callable-valued capabilities."""

    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self._findings: set[MutationSurface] = set()
        self._scopes: list[tuple[_ScopeKind, dict[str, str]]] = [("global", {})]

    @property
    def findings(self) -> tuple[MutationSurface, ...]:
        return tuple(sorted(self._findings))

    def _record(self, node: ast.AST, kind: str, name: str) -> None:
        self._findings.add(
            MutationSurface(str(self._path), getattr(node, "lineno", 0), kind, name)
        )

    def _resolved(self, expression: ast.expr) -> str | None:
        return resolved_expression(expression, self._scopes[-1][1])

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        aliases = self._scopes[-1][1]
        if isinstance(target, ast.Name):
            resolved = self._resolved(value)
            if resolved is None:
                aliases[target.id] = SHADOWED_NAME
                return
            aliases[target.id] = resolved
            if is_dangerous_call(resolved) or is_mutation_name(resolved):
                self._record(target, "python-dangerous-alias", resolved)
            return
        if isinstance(target, (ast.Tuple, ast.List)) and isinstance(
            value, (ast.Tuple, ast.List)
        ):
            for nested_target, nested_value in zip(
                target.elts, value.elts, strict=False
            ):
                self._bind(nested_target, nested_value)

    def _child_function_scope(
        self,
        arguments: ast.arguments,
        function_name: str | None = None,
    ) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for kind, scope in self._scopes:
            if kind != "class":
                aliases.update(scope)
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            aliases[argument.arg] = SHADOWED_NAME
        if arguments.vararg is not None:
            aliases[arguments.vararg.arg] = SHADOWED_NAME
        if arguments.kwarg is not None:
            aliases[arguments.kwarg.arg] = SHADOWED_NAME
        if function_name is not None:
            aliases[function_name] = SHADOWED_NAME
        return aliases

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
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        for argument in arguments:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        self._scopes[-1][1][node.name] = SHADOWED_NAME
        self._scopes.append(
            ("function", self._child_function_scope(node.args, node.name))
        )
        for statement in node.body:
            self.visit(statement)
        _ = self._scopes.pop()

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._scopes.append(("function", self._child_function_scope(node.args)))
        self.visit(node.body)
        _ = self._scopes.pop()

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._scopes[-1][1][node.name] = SHADOWED_NAME
        inherited = dict(self._scopes[-1][1])
        self._scopes.append(("class", inherited))
        for statement in node.body:
            if (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and is_mutation_name(statement.target.id)
            ):
                self._record(statement, "python-field", statement.target.id)
            self.visit(statement)
        _ = self._scopes.pop()

    @override
    def visit_Import(self, node: ast.Import) -> None:
        for imported in node.names:
            local = imported.asname or imported.name.split(".")[0]
            self._scopes[-1][1][local] = imported.name

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for imported in node.names:
            origin = f"{module}.{imported.name}" if module else imported.name
            local = imported.asname or imported.name
            self._scopes[-1][1][local] = origin
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
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)
            self._bind(target, node.value)
        if isinstance(node.value, ast.Lambda):
            for target in node.targets:
                if isinstance(target, ast.Name) and is_mutation_name(target.id):
                    self._record(node, "python-lambda", target.id)

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)
            self._bind(node.target, node.value)
            if (
                isinstance(node.target, ast.Name)
                and isinstance(node.value, ast.Lambda)
                and is_mutation_name(node.target.id)
            ):
                self._record(node, "python-lambda", node.target.id)

    @override
    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.visit(node.target)
        self._bind(node.target, node.value)


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
