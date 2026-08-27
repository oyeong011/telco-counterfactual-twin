"""RFC 8785 canonical JSON for signed and hashed contract bytes."""

from __future__ import annotations

from typing import Final

import rfc8785
from pydantic import BaseModel, JsonValue, TypeAdapter

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def canonical_json_bytes(value: JsonValue) -> bytes:
    """Serialize one I-JSON value using RFC 8785 JCS."""
    return rfc8785.dumps(value)


def canonical_model_bytes(model: BaseModel, *, exclude: frozenset[str] | None = None) -> bytes:
    """Serialize a Pydantic contract with explicitly excluded signed fields."""
    value = JSON_VALUE_ADAPTER.validate_python(
        model.model_dump(
            mode="json",
            exclude=None if exclude is None else set(exclude),
            exclude_none=True,
        )
    )
    return canonical_json_bytes(value)
