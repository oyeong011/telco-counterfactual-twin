"""AST-derived MCP SDK signature checks for the pinned vendor snapshot."""

from __future__ import annotations

import ast
import tarfile
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class SignatureTarget:
    """One class/function signature expected in the MCP SDK source."""

    path: str
    class_name: str | None
    function_name: str
    qualified_name: str
    annotated_arguments: frozenset[str] | None = None


SIGNATURE_TARGETS: Final = {
    "asgi_app_call": SignatureTarget(
        "mcp/server/streamable_http_manager.py",
        "StreamableHTTPASGIApp",
        "__call__",
        "StreamableHTTPASGIApp.__call__",
    ),
    "default_lifespan": SignatureTarget(
        "mcp/server/lowlevel/server.py",
        None,
        "lifespan",
        "lifespan",
    ),
    "server_run": SignatureTarget(
        "mcp/server/lowlevel/server.py",
        "Server",
        "run",
        "Server.run",
        annotated_arguments=frozenset({"raise_exceptions"}),
    ),
    "server_streamable_http_app": SignatureTarget(
        "mcp/server/lowlevel/server.py",
        "Server",
        "streamable_http_app",
        "Server.streamable_http_app",
    ),
    "session_manager_handle_request": SignatureTarget(
        "mcp/server/streamable_http_manager.py",
        "StreamableHTTPSessionManager",
        "handle_request",
        "StreamableHTTPSessionManager.handle_request",
    ),
    "session_manager_init": SignatureTarget(
        "mcp/server/streamable_http_manager.py",
        "StreamableHTTPSessionManager",
        "__init__",
        "StreamableHTTPSessionManager.__init__",
        annotated_arguments=frozenset(),
    ),
    "session_manager_run": SignatureTarget(
        "mcp/server/streamable_http_manager.py",
        "StreamableHTTPSessionManager",
        "run",
        "StreamableHTTPSessionManager.run",
    ),
    "stdio_server": SignatureTarget(
        "mcp/server/stdio.py",
        None,
        "stdio_server",
        "stdio_server",
    ),
    "transport_handle_request": SignatureTarget(
        "mcp/server/streamable_http.py",
        "StreamableHTTPServerTransport",
        "handle_request",
        "StreamableHTTPServerTransport.handle_request",
    ),
}


def derive_wheel_signatures(path: Path) -> dict[str, str]:
    """Derive normalized signature strings from wheel Python source members."""
    with zipfile.ZipFile(path) as archive:
        return {
            key: _signature_from_source(archive.read(target.path), target)
            for key, target in SIGNATURE_TARGETS.items()
        }


def derive_sdist_signatures(path: Path) -> dict[str, str]:
    """Derive normalized signature strings from sdist Python source members."""
    with tarfile.open(path, "r:gz") as archive:
        signatures: dict[str, str] = {}
        for key, target in SIGNATURE_TARGETS.items():
            member = archive.extractfile(f"mcp-2.1.1/src/{target.path}")
            if member is None:
                message = f"sdist signature source missing: {target.path}"
                raise ValueError(message)
            signatures[key] = _signature_from_source(member.read(), target)
        return signatures


def normalize_signature(value: str) -> str:
    """Normalize harmless formatting variance in stored signature strings."""
    return " ".join(value.replace('"', "'").split())


def _signature_from_source(source: bytes, target: SignatureTarget) -> str:
    module = ast.parse(source)
    node = _find_function(module, target)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    arguments = _format_arguments(
        node.args,
        drop_self=target.class_name is not None,
        annotated_arguments=target.annotated_arguments,
    )
    returns = "" if node.returns is None else f" -> {ast.unparse(node.returns)}"
    return normalize_signature(f"{prefix} {target.qualified_name}({arguments}){returns}")


def _find_function(module: ast.Module, target: SignatureTarget) -> FunctionNode:
    body = module.body if target.class_name is None else _find_class(module, target.class_name).body
    for node in body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == target.function_name
        ):
            return node
    message = f"signature target missing: {target.qualified_name}"
    raise ValueError(message)


def _find_class(module: ast.Module, class_name: str) -> ast.ClassDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    message = f"signature class missing: {class_name}"
    raise ValueError(message)


def _format_arguments(
    arguments: ast.arguments,
    drop_self: bool,
    annotated_arguments: frozenset[str] | None,
) -> str:
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults: list[ast.expr | None] = [
        *([None] * (len(positional) - len(arguments.defaults))),
        *arguments.defaults,
    ]
    paired = list(zip(positional, defaults, strict=True))
    if drop_self and paired and paired[0][0].arg == "self":
        paired = paired[1:]
    parts = [_format_arg(arg, default, annotated_arguments) for arg, default in paired]
    if arguments.vararg is not None:
        parts.append(_format_star_arg("*", arguments.vararg, annotated_arguments))
    elif arguments.kwonlyargs:
        parts.append("*")
    parts.extend(
        _format_arg(arg, default, annotated_arguments)
        for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
    )
    if arguments.kwarg is not None:
        parts.append(_format_star_arg("**", arguments.kwarg, annotated_arguments))
    return ", ".join(parts)


def _format_arg(
    arg: ast.arg,
    default: ast.expr | None,
    annotated_arguments: frozenset[str] | None,
) -> str:
    annotation = _format_annotation(arg, annotated_arguments)
    default_joiner = " = " if annotation else "="
    default_text = "" if default is None else f"{default_joiner}{ast.unparse(default)}"
    return f"{arg.arg}{annotation}{default_text}"


def _format_star_arg(
    prefix: str,
    arg: ast.arg,
    annotated_arguments: frozenset[str] | None,
) -> str:
    annotation = _format_annotation(arg, annotated_arguments)
    return f"{prefix}{arg.arg}{annotation}"


def _format_annotation(arg: ast.arg, annotated_arguments: frozenset[str] | None) -> str:
    include = annotated_arguments is None or arg.arg in annotated_arguments
    return "" if arg.annotation is None or not include else f": {ast.unparse(arg.annotation)}"
