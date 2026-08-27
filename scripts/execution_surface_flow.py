"""Conservative statement exit states for execution-surface scanning."""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from functools import singledispatch

from scripts.execution_surface_bindings import AliasTable, ScopeFrame
from scripts.execution_surface_values import (
    SHADOWED_PROVENANCE,
    ValueProvenance,
    dangerous_leaf,
)


@dataclass(frozen=True, slots=True)
class StatementExits:
    """Normal, break, and continue aliases leaving one statement sequence."""

    normal: AliasTable | None
    breaks: tuple[AliasTable, ...]
    continues: tuple[AliasTable, ...]


@dataclass(frozen=True, slots=True)
class FlowAnalysisContext:
    """Visitor and lexical scope access for isolated statement analysis."""

    visitor: ast.NodeVisitor
    scopes: list[ScopeFrame]

    def scan_node(self, node: ast.AST, initial: AliasTable) -> AliasTable:
        """Visit one ordinary node against an isolated alias state."""
        previous = self.scopes[-1]
        self.scopes[-1] = (previous[0], dict(initial))
        try:
            self.visitor.visit(node)
            result = dict(self.scopes[-1][1])
        finally:
            self.scopes[-1] = previous
        return result

    def scan_statements(
        self,
        statements: tuple[ast.stmt, ...],
        initial: AliasTable,
    ) -> StatementExits:
        """Scan sequential statements, stopping each active transfer path."""
        normal: AliasTable | None = dict(initial)
        unreachable_seed = dict(initial)
        breaks: list[AliasTable] = []
        continues: list[AliasTable] = []
        for statement in statements:
            if normal is None:
                _ = _statement_exits(statement, self, unreachable_seed)
                continue
            unreachable_seed = normal
            exits = _statement_exits(statement, self, normal)
            breaks.extend(exits.breaks)
            continues.extend(exits.continues)
            normal = exits.normal
        return StatementExits(normal, tuple(breaks), tuple(continues))


def _merge_value(left: ValueProvenance, right: ValueProvenance) -> ValueProvenance:
    if left == right:
        return left
    return dangerous_leaf(left) or dangerous_leaf(right) or SHADOWED_PROVENANCE


def merge_aliases(left: AliasTable, right: AliasTable) -> AliasTable:
    """Merge two reachable alias states, retaining danger from either path."""
    keys = left.keys() | right.keys()
    return {
        key: _merge_value(
            left.get(key, SHADOWED_PROVENANCE),
            right.get(key, SHADOWED_PROVENANCE),
        )
        for key in keys
    }


def merge_states(states: Iterable[AliasTable]) -> AliasTable | None:
    """Merge zero or more reachable alias states."""
    iterator = iter(states)
    merged = next(iterator, None)
    if merged is None:
        return None
    result = dict(merged)
    for state in iterator:
        result = merge_aliases(result, state)
    return result


def exits_state(exits: StatementExits) -> AliasTable | None:
    """Merge every reachable exit category from one statement sequence."""
    normal = () if exits.normal is None else (exits.normal,)
    return merge_states((*normal, *exits.breaks, *exits.continues))


@singledispatch
def _statement_exits(
    statement: ast.stmt,
    context: FlowAnalysisContext,
    initial: AliasTable,
) -> StatementExits:
    return StatementExits(context.scan_node(statement, initial), (), ())


def _break_exits(
    _statement: ast.Break,
    _context: FlowAnalysisContext,
    initial: AliasTable,
) -> StatementExits:
    return StatementExits(None, (dict(initial),), ())


def _continue_exits(
    _statement: ast.Continue,
    _context: FlowAnalysisContext,
    initial: AliasTable,
) -> StatementExits:
    return StatementExits(None, (), (dict(initial),))


def _if_exits(
    statement: ast.If,
    context: FlowAnalysisContext,
    initial: AliasTable,
) -> StatementExits:
    after_test = context.scan_node(statement.test, initial)
    truthy = context.scan_statements(tuple(statement.body), after_test)
    falsy = (
        context.scan_statements(tuple(statement.orelse), after_test)
        if statement.orelse
        else StatementExits(after_test, (), ())
    )
    normal_candidates = tuple(
        state for state in (truthy.normal, falsy.normal) if state is not None
    )
    return StatementExits(
        merge_states(normal_candidates),
        (*truthy.breaks, *falsy.breaks),
        (*truthy.continues, *falsy.continues),
    )


_ = _statement_exits.register(ast.Break, _break_exits)
_ = _statement_exits.register(ast.Continue, _continue_exits)
_ = _statement_exits.register(ast.If, _if_exits)
