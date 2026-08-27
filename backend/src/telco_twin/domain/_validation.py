"""Stable validation errors shared by Twin contract boundaries."""

from typing import LiteralString, Never

from pydantic_core import PydanticCustomError


def fail_validation(code: LiteralString, message: LiteralString) -> Never:
    """Raise one stable Pydantic boundary error."""
    raise PydanticCustomError(code, message)
