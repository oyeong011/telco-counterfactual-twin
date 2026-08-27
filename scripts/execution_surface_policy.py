"""Identifier and callable-origin policy for execution-surface scanning."""

from __future__ import annotations

import re
from typing import Final

CAMEL_BOUNDARY: Final = re.compile(r"([a-z0-9])([A-Z])")
SEPARATOR: Final = re.compile(r"[^A-Za-z0-9]+")
DIRECT_TOKENS: Final = frozenset(
    {"callback", "command", "execute", "execution", "revoke", "revocation", "shell"}
)
MUTATION_VERBS: Final = frozenset({"apply", "commit", "execute", "push", "revoke"})
DANGEROUS_CALLS: Final = frozenset(
    {
        "__import__",
        "builtins.__import__",
        "builtins.compile",
        "builtins.eval",
        "builtins.exec",
        "compile",
        "eval",
        "exec",
        "importlib.import_module",
        "os.popen",
        "os.system",
        "runpy.run_module",
        "runpy.run_path",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "subprocess.Popen",
        "subprocess.run",
    }
)


def _tokens(name: str) -> frozenset[str]:
    expanded = CAMEL_BOUNDARY.sub(r"\1_\2", name)
    return frozenset(item.lower() for item in SEPARATOR.split(expanded) if item)


def is_mutation_name(name: str) -> bool:
    """Return whether one qualified identifier exposes mutation authority."""
    tokens = _tokens(name)
    if tokens & DIRECT_TOKENS:
        return True
    return bool(tokens & MUTATION_VERBS) and bool(
        tokens & {"approval", "config", "network", "operation", "patch", "payload"}
    )


def is_dangerous_call(name: str) -> bool:
    """Return whether one resolved callable can execute dynamic/process code."""
    return name in DANGEROUS_CALLS or name.startswith(("os.exec", "os.spawn"))
