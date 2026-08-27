"""Lexical scope and assignment bindings for execution-surface provenance."""

from __future__ import annotations

import ast
from functools import singledispatch
from typing import Literal

from scripts.execution_surface_values import (
    SHADOWED_PROVENANCE,
    CollectionProvenance,
    ValueProvenance,
    dangerous_leaf,
)

type ScopeKind = Literal["global", "function", "class"]
type AliasTable = dict[str, ValueProvenance]
type ScopeFrame = tuple[ScopeKind, AliasTable]
type TargetBinding = tuple[str, ValueProvenance]


def child_function_scope(
    scopes: list[ScopeFrame],
    arguments: ast.arguments,
    function_name: str | None = None,
) -> AliasTable:
    """Create a lexical child scope excluding non-enclosing class names."""
    aliases: AliasTable = {}
    for kind, scope in scopes:
        if kind != "class":
            aliases.update(scope)
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
    ):
        aliases[argument.arg] = SHADOWED_PROVENANCE
    if arguments.vararg is not None:
        aliases[arguments.vararg.arg] = SHADOWED_PROVENANCE
    if arguments.kwarg is not None:
        aliases[arguments.kwarg.arg] = SHADOWED_PROVENANCE
    if function_name is not None:
        aliases[function_name] = SHADOWED_PROVENANCE
    return aliases


def target_bindings(
    target: ast.expr,
    value: ValueProvenance,
) -> tuple[TargetBinding, ...]:
    """Resolve one assignment/destructuring target into immutable bindings."""
    if isinstance(target, ast.Name):
        return ((target.id, value),)
    if isinstance(target, (ast.Tuple, ast.List)):
        if isinstance(value, CollectionProvenance) and len(target.elts) == len(
            value.values
        ):
            return tuple(
                binding
                for nested_target, nested_value in zip(
                    target.elts, value.values, strict=True
                )
                for binding in target_bindings(nested_target, nested_value)
            )
        return tuple(
            binding
            for nested_target in target.elts
            for binding in target_bindings(nested_target, SHADOWED_PROVENANCE)
        )
    return ()


@singledispatch
def iteration_provenance(_value: ValueProvenance) -> ValueProvenance:
    """Conservatively resolve one clear static collection iteration value."""
    return SHADOWED_PROVENANCE


def _collection_iteration(value: CollectionProvenance) -> ValueProvenance:
    if len(value.values) == 1:
        return value.values[0]
    dangerous = dangerous_leaf(value)
    if dangerous is not None:
        return dangerous
    return SHADOWED_PROVENANCE


_ = iteration_provenance.register(CollectionProvenance, _collection_iteration)
