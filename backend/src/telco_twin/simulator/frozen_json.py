"""Recursive immutable containers for canonical simulator JSON."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Never, assert_never, overload, override

from pydantic import JsonValue, TypeAdapter

from telco_twin.domain._contract import validate_safe_key

type JsonObject = dict[str, JsonValue]
type FrozenJsonScalar = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class FrozenJsonMutationError(TypeError):
    """A caller attempted to mutate a frozen JSON container."""

    container: str

    @override
    def __str__(self) -> str:
        """Return a stable immutable-container diagnostic."""
        return f"frozen JSON {self.container} is immutable"


@dataclass(frozen=True, slots=True)
class EventPayloadShapeError(ValueError):
    """An event payload root was not a JSON object."""

    actual_type: str

    @override
    def __str__(self) -> str:
        """Return a stable payload-root diagnostic."""
        return f"event payload must be an object, received {self.actual_type}"


@dataclass(frozen=True, slots=True)
class FrozenJsonMap(Mapping[str, "FrozenJsonValue"]):
    """Fixed-order immutable JSON object."""

    _entries: tuple[tuple[str, FrozenJsonValue], ...]

    @override
    def __getitem__(self, key: str) -> FrozenJsonValue:
        """Return one value by key."""
        for candidate, value in self._entries:
            if candidate == key:
                return value
        raise KeyError(key)

    @override
    def __iter__(self) -> Iterator[str]:
        """Iterate keys in canonical lexical order."""
        return (key for key, _ in self._entries)

    @override
    def __len__(self) -> int:
        """Return the fixed entry count."""
        return len(self._entries)

    def __setitem__(self, key: str, value: FrozenJsonValue) -> Never:
        """Reject mutation through mapping syntax."""
        raise FrozenJsonMutationError(container="mapping")


@dataclass(frozen=True, slots=True)
class FrozenJsonList(Sequence["FrozenJsonValue"]):
    """Immutable JSON array backed by a tuple."""

    _values: tuple[FrozenJsonValue, ...]

    @overload
    def __getitem__(self, index: int) -> FrozenJsonValue: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[FrozenJsonValue, ...]: ...

    @override
    def __getitem__(
        self,
        index: int | slice,
    ) -> FrozenJsonValue | tuple[FrozenJsonValue, ...]:
        """Return one value or immutable slice."""
        return self._values[index]

    @override
    def __len__(self) -> int:
        """Return the fixed array length."""
        return len(self._values)

    def __setitem__(self, index: int, value: FrozenJsonValue) -> Never:
        """Reject mutation through sequence syntax."""
        raise FrozenJsonMutationError(container="list")


type FrozenJsonValue = FrozenJsonScalar | FrozenJsonMap | FrozenJsonList

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


def _freeze_json(value: JsonValue) -> FrozenJsonValue:
    match value:
        case dict() as mapping:
            return FrozenJsonMap(
                tuple(
                    (validate_safe_key(key), _freeze_json(mapping[key])) for key in sorted(mapping)
                )
            )
        case list() as values:
            return FrozenJsonList(tuple(_freeze_json(item) for item in values))
        case bool() as scalar:
            return scalar
        case str() | int() | float() as scalar:
            return scalar
        case _ as unreachable:
            if unreachable is None:
                return None
            assert_never(unreachable)


def _thaw_json(value: FrozenJsonValue) -> JsonValue:
    match value:
        case FrozenJsonMap() as mapping:
            return {key: _thaw_json(item) for key, item in mapping.items()}
        case FrozenJsonList() as values:
            return [_thaw_json(item) for item in values]
        case bool() as scalar:
            return scalar
        case str() | int() | float() as scalar:
            return scalar
        case _ as unreachable:
            if unreachable is None:
                return None
            assert_never(unreachable)


def thaw_payload(value: FrozenJsonMap) -> JsonObject:
    """Return a detached mutable JSON object."""
    return {key: _thaw_json(item) for key, item in value.items()}


def freeze_payload(value: JsonValue) -> FrozenJsonMap:
    """Parse one JSON object into a recursive immutable value."""
    frozen = _freeze_json(value)
    match frozen:
        case FrozenJsonMap() as mapping:
            return mapping
        case FrozenJsonList() | bool() | str() | int() | float():
            raise EventPayloadShapeError(actual_type=type(frozen).__name__)
        case _ as unreachable:
            if unreachable is None:
                raise EventPayloadShapeError(actual_type="NoneType")
            assert_never(unreachable)
