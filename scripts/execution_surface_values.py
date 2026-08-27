"""Immutable static-value provenance for execution-surface scanning."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from functools import singledispatch
from typing import Final

from scripts.execution_surface_policy import (
    DANGEROUS_CALLS,
    is_dangerous_call,
    is_mutation_name,
)

SHADOWED_NAME: Final = "<shadowed>"


@dataclass(frozen=True, slots=True)
class ScalarProvenance:
    """One statically resolved qualified value origin."""

    name: str


@dataclass(frozen=True, slots=True)
class CollectionProvenance:
    """One list, tuple, or set with recursively resolved members."""

    values: tuple[ValueProvenance, ...]
    indexable: bool


@dataclass(frozen=True, slots=True)
class MappingProvenance:
    """One dictionary with constant-key and expanded/unknown members."""

    entries: tuple[tuple[str, ValueProvenance], ...]
    unknown_values: tuple[ValueProvenance, ...]


type ValueProvenance = ScalarProvenance | CollectionProvenance | MappingProvenance
type ProvenanceMap = Mapping[str, ValueProvenance]
SHADOWED_PROVENANCE: Final = ScalarProvenance(SHADOWED_NAME)


@singledispatch
def scalar_name(_value: ValueProvenance) -> str | None:
    """Return the resolved qualified name only for a scalar provenance."""
    return None


def _scalar_name(value: ScalarProvenance) -> str:
    return value.name


_ = scalar_name.register(ScalarProvenance, _scalar_name)


def _is_capability_origin(name: str) -> bool:
    prefix = f"{name}."
    return (
        is_dangerous_call(name)
        or is_mutation_name(name)
        or any(candidate.startswith(prefix) for candidate in DANGEROUS_CALLS)
    )


@singledispatch
def dangerous_leaf(_value: ValueProvenance) -> ScalarProvenance | None:
    """Return one deterministic dangerous descendant, if the value may hold one."""
    return None


def _dangerous_scalar(value: ScalarProvenance) -> ScalarProvenance | None:
    return value if _is_capability_origin(value.name) else None


def _first_dangerous(
    candidates: tuple[ValueProvenance, ...],
) -> ScalarProvenance | None:
    for candidate in candidates:
        dangerous = dangerous_leaf(candidate)
        if dangerous is not None:
            return dangerous
    return None


def _dangerous_collection(value: CollectionProvenance) -> ScalarProvenance | None:
    return _first_dangerous(value.values)


def _dangerous_mapping(value: MappingProvenance) -> ScalarProvenance | None:
    candidates = (
        *(entry_value for _, entry_value in value.entries),
        *value.unknown_values,
    )
    return _first_dangerous(candidates)


_ = dangerous_leaf.register(ScalarProvenance, _dangerous_scalar)
_ = dangerous_leaf.register(CollectionProvenance, _dangerous_collection)
_ = dangerous_leaf.register(MappingProvenance, _dangerous_mapping)


def _constant_key(expression: ast.expr) -> str | None:
    if not isinstance(expression, ast.Constant):
        return None
    return ast.dump(expression, annotate_fields=True, include_attributes=False)


def _constant_index(expression: ast.expr) -> int | None:
    if isinstance(expression, ast.Constant):
        value = expression.value
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    if (
        isinstance(expression, ast.UnaryOp)
        and isinstance(expression.op, ast.USub)
        and isinstance(expression.operand, ast.Constant)
    ):
        value = expression.operand.value
        if isinstance(value, int) and not isinstance(value, bool):
            return -value
    return None


@singledispatch
def expression_provenance(
    _expression: ast.expr,
    _aliases: ProvenanceMap,
) -> ValueProvenance:
    """Resolve one supported expression into immutable scalar/container provenance."""
    return SHADOWED_PROVENANCE


def _name_provenance(
    expression: ast.Name,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    return aliases.get(expression.id, ScalarProvenance(expression.id))


def _attribute_provenance(
    expression: ast.Attribute,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    base = scalar_name(expression_provenance(expression.value, aliases))
    return (
        SHADOWED_PROVENANCE
        if base is None
        else ScalarProvenance(f"{base}.{expression.attr}")
    )


def _sequence_provenance(
    expression: ast.List | ast.Tuple,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    return CollectionProvenance(
        tuple(expression_provenance(item, aliases) for item in expression.elts),
        indexable=True,
    )


def _set_provenance(
    expression: ast.Set,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    return CollectionProvenance(
        tuple(expression_provenance(item, aliases) for item in expression.elts),
        indexable=False,
    )


def _mapping_provenance(
    expression: ast.Dict,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    entries: list[tuple[str, ValueProvenance]] = []
    unknown_values: list[ValueProvenance] = []
    for key, item in zip(expression.keys, expression.values, strict=True):
        value = expression_provenance(item, aliases)
        token = None if key is None else _constant_key(key)
        if token is None:
            unknown_values.append(value)
        else:
            entries.append((token, value))
    return MappingProvenance(tuple(entries), tuple(unknown_values))


@singledispatch
def _selected_provenance(
    _container: ValueProvenance,
    _selection: ast.expr,
) -> ValueProvenance:
    return SHADOWED_PROVENANCE


def _selected_collection(
    container: CollectionProvenance,
    selection: ast.expr,
) -> ValueProvenance:
    if not container.indexable:
        return SHADOWED_PROVENANCE
    index = _constant_index(selection)
    if index is not None and -len(container.values) <= index < len(container.values):
        return container.values[index]
    return dangerous_leaf(container) or SHADOWED_PROVENANCE


def _selected_mapping(
    container: MappingProvenance,
    selection: ast.expr,
) -> ValueProvenance:
    key = _constant_key(selection)
    if key is not None:
        for token, value in container.entries:
            if token == key:
                return value
    return dangerous_leaf(container) or SHADOWED_PROVENANCE


_ = _selected_provenance.register(CollectionProvenance, _selected_collection)
_ = _selected_provenance.register(MappingProvenance, _selected_mapping)


def _subscript_provenance(
    expression: ast.Subscript,
    aliases: ProvenanceMap,
) -> ValueProvenance:
    return _selected_provenance(
        expression_provenance(expression.value, aliases),
        expression.slice,
    )


_ = expression_provenance.register(ast.Name, _name_provenance)
_ = expression_provenance.register(ast.Attribute, _attribute_provenance)
_ = expression_provenance.register(ast.List, _sequence_provenance)
_ = expression_provenance.register(ast.Tuple, _sequence_provenance)
_ = expression_provenance.register(ast.Set, _set_provenance)
_ = expression_provenance.register(ast.Dict, _mapping_provenance)
_ = expression_provenance.register(ast.Subscript, _subscript_provenance)


def resolved_name(expression: ast.expr, aliases: ProvenanceMap) -> str | None:
    """Resolve a supported scalar expression through static provenance."""
    return scalar_name(expression_provenance(expression, aliases))
