"""AST capability discovery for Python execution surfaces."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import final, override

from scripts.execution_surface_bindings import (
    ScopeFrame,
    child_function_scope,
    iteration_provenance,
    target_bindings,
)
from scripts.execution_surface_policy import (
    is_dangerous_call,
    is_mutation_name,
)
from scripts.execution_surface_types import MutationSurface
from scripts.execution_surface_values import (
    SHADOWED_PROVENANCE,
    ScalarProvenance,
    ValueProvenance,
    dangerous_leaf,
    expression_provenance,
    resolved_name,
    scalar_name,
)


@final
class _PythonSurfaceVisitor(ast.NodeVisitor):
    """Track qualified callables, aliases, and callable-valued capabilities."""

    def __init__(self, path: Path) -> None:
        self._path: Path = path
        self._findings: set[MutationSurface] = set()
        self._scopes: list[ScopeFrame] = [("global", {})]

    @property
    def findings(self) -> tuple[MutationSurface, ...]:
        return tuple(sorted(self._findings))

    def _record(self, node: ast.AST, kind: str, name: str) -> None:
        self._findings.add(
            MutationSurface(str(self._path), getattr(node, "lineno", 0), kind, name)
        )

    def _resolved(self, expression: ast.expr) -> str | None:
        return resolved_name(expression, self._scopes[-1][1])

    def _provenance(self, expression: ast.expr) -> ValueProvenance:
        return expression_provenance(expression, self._scopes[-1][1])

    def _bind(self, target: ast.expr, value: ValueProvenance) -> None:
        aliases = self._scopes[-1][1]
        for name, provenance in target_bindings(target, value):
            aliases[name] = provenance
            resolved = scalar_name(provenance)
            if resolved is None:
                continue
            if is_dangerous_call(resolved) or is_mutation_name(resolved):
                self._record(target, "python-dangerous-alias", resolved)

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
        self._scopes[-1][1][node.name] = SHADOWED_PROVENANCE
        self._scopes.append(
            ("function", child_function_scope(self._scopes, node.args, node.name))
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
        self._scopes.append(("function", child_function_scope(self._scopes, node.args)))
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
        self._scopes[-1][1][node.name] = SHADOWED_PROVENANCE
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
            self._scopes[-1][1][local] = ScalarProvenance(imported.name)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for imported in node.names:
            origin = f"{module}.{imported.name}" if module else imported.name
            local = imported.asname or imported.name
            self._scopes[-1][1][local] = ScalarProvenance(origin)
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
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_reference(node)
            resolved = self._resolved(node)
            dangerous = dangerous_leaf(self._provenance(node))
            if dangerous is not None and (
                resolved is None
                or not (is_dangerous_call(resolved) or is_mutation_name(resolved))
            ):
                self._record(node, "python-dangerous-container", dangerous.name)
        self.generic_visit(node)

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        value = self._provenance(node.value)
        for target in node.targets:
            self.visit(target)
            self._bind(target, value)
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
            self._bind(node.target, self._provenance(node.value))
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
        self._bind(node.target, self._provenance(node.value))

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.visit(node.target)
        self._bind(node.target, iteration_provenance(self._provenance(node.iter)))
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    @override
    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)


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
