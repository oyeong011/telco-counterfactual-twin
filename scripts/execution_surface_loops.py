"""Cardinality-aware loop state analysis for execution-surface scanning."""

from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

from scripts.execution_surface_bindings import (
    AliasTable,
    ScopeFrame,
    iteration_provenance,
)
from scripts.execution_surface_flow import (
    FlowAnalysisContext,
    exits_state,
    merge_aliases,
    merge_states,
)
from scripts.execution_surface_values import (
    SHADOWED_PROVENANCE,
    CollectionProvenance,
    MappingProvenance,
    ValueProvenance,
)

type TargetBinder = Callable[[ast.expr, ValueProvenance], None]


@dataclass(frozen=True, slots=True)
class LoopSource:
    """Static cardinality plus possible and normal-last element provenance."""

    can_iterate: bool
    can_skip: bool
    possible_element: ValueProvenance
    last_element: ValueProvenance


@dataclass(frozen=True, slots=True)
class LoopAnalysisContext:
    """Visitor callbacks and lexical scopes shared by one loop analysis."""

    visitor: ast.NodeVisitor
    scopes: list[ScopeFrame]
    bind_target: TargetBinder

    def target_state(
        self,
        target: ast.expr,
        value: ValueProvenance,
        initial: AliasTable,
    ) -> AliasTable:
        previous = self.scopes[-1]
        self.scopes[-1] = (previous[0], dict(initial))
        try:
            self.visitor.visit(target)
            self.bind_target(target, value)
            result = dict(self.scopes[-1][1])
        finally:
            self.scopes[-1] = previous
        return result


def _literal_int(expression: ast.expr) -> int | None:
    if not isinstance(expression, ast.Constant):
        return None
    value = expression.value
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _range_source(expression: ast.Call) -> LoopSource | None:
    if not isinstance(expression.func, ast.Name) or expression.func.id != "range":
        return None
    if expression.keywords or not 1 <= len(expression.args) <= 3:
        return None
    arguments = tuple(_literal_int(argument) for argument in expression.args)
    if any(argument is None for argument in arguments):
        return None
    values = tuple(argument for argument in arguments if argument is not None)
    start, stop, step = (
        (0, values[0], 1)
        if len(values) == 1
        else (
            values[0],
            values[1],
            1 if len(values) == 2 else values[2],
        )
    )
    if step == 0:
        return None
    empty = start >= stop if step > 0 else start <= stop
    return LoopSource(not empty, empty, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)


def _call_source(expression: ast.expr) -> LoopSource | None:
    if not isinstance(expression, ast.Call):
        return None
    ranged = _range_source(expression)
    if ranged is not None:
        return ranged
    if (
        isinstance(expression.func, ast.Name)
        and expression.func.id == "set"
        and not expression.args
        and not expression.keywords
    ):
        return LoopSource(False, True, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)
    return None


def loop_source(expression: ast.expr, value: ValueProvenance) -> LoopSource:
    """Classify one iterable as empty, nonempty, or maybe empty."""
    called = _call_source(expression)
    if called is not None:
        return called
    if isinstance(value, CollectionProvenance):
        if not value.values:
            return LoopSource(False, True, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)
        possible = iteration_provenance(value)
        last = value.values[-1] if value.indexable else possible
        return LoopSource(True, False, possible, last)
    if isinstance(value, MappingProvenance):
        if not value.entries and not value.unknown_values:
            return LoopSource(False, True, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)
        can_skip = not value.entries
        return LoopSource(True, can_skip, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)
    return LoopSource(True, True, SHADOWED_PROVENANCE, SHADOWED_PROVENANCE)


def visit_for_loop(
    context: LoopAnalysisContext,
    node: ast.For | ast.AsyncFor,
    iterable: ValueProvenance,
) -> None:
    """Visit one loop and conservatively replace the current exit alias state."""
    before = dict(context.scopes[-1][1])
    source = loop_source(node.iter, iterable)
    flow = FlowAnalysisContext(context.visitor, context.scopes)
    if not source.can_iterate:
        _ = flow.scan_statements(tuple(node.body), before)
        after = exits_state(flow.scan_statements(tuple(node.orelse), before))
    else:
        possible_entry = context.target_state(
            node.target, source.possible_element, before
        )
        last_entry = context.target_state(node.target, source.last_element, before)
        possible_exits = flow.scan_statements(tuple(node.body), possible_entry)
        last_exits = flow.scan_statements(tuple(node.body), last_entry)
        normal_candidates = tuple(
            state
            for state in (last_exits.normal, *last_exits.continues)
            if state is not None
        )
        normal_exit = merge_states(normal_candidates)
        if source.can_skip:
            normal_exit = (
                before if normal_exit is None else merge_aliases(before, normal_exit)
            )
        if normal_exit is None:
            _ = flow.scan_statements(tuple(node.orelse), before)
            after_else = None
        else:
            after_else = exits_state(
                flow.scan_statements(tuple(node.orelse), normal_exit)
            )
        break_exit = merge_states(possible_exits.breaks)
        after = merge_states(
            state for state in (break_exit, after_else) if state is not None
        )
    if after is None:
        after = before
    current = context.scopes[-1][1]
    current.clear()
    current.update(after)
