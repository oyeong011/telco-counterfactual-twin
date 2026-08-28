#!/usr/bin/env -S uv run --project backend python
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["pydantic==2.13.4"]
# ///
# pyright: reportUnusedFunction=false

# ─── How to run ───
# Imported by visual_qa_checks.py; run the wrapper instead.
# ────────────────

"""Complete bounded PNG chunk and scanline validation."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts import visual_qa_types as types
from scripts.visual_qa_types import VisualQaError

MAX_DECODED_BYTES: Final = 128 * 1024 * 1024
MAX_ENCODED_BYTES: Final = 64 * 1024 * 1024
CHANNELS: Final = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ALLOWED_DEPTHS: Final = {
    0: frozenset({1, 2, 4, 8, 16}),
    2: frozenset({8, 16}),
    3: frozenset({1, 2, 4, 8}),
    4: frozenset({8, 16}),
    6: frozenset({8, 16}),
}


@dataclass(frozen=True, slots=True)
class PngShape:
    """Decoded non-interlaced PNG geometry and scanline size."""

    width: int
    height: int
    row_bytes: int
    bit_depth: int
    color_type: int


def _shape(data: bytes, path: Path) -> PngShape:
    if len(data) != 13:
        raise VisualQaError("invalid-png", path.as_posix())
    width, height, bit_depth, color_type, compression, filter_method, interlace = (
        struct.unpack(">IIBBBBB", data)
    )
    depths = ALLOWED_DEPTHS.get(color_type)
    if (
        width < 1
        or height < 1
        or depths is None
        or bit_depth not in depths
        or compression != 0
        or filter_method != 0
        or interlace != 0
    ):
        raise VisualQaError("invalid-png", path.as_posix())
    row_bytes = (width * CHANNELS[color_type] * bit_depth + 7) // 8
    expected = height * (row_bytes + 1)
    if expected > MAX_DECODED_BYTES:
        raise VisualQaError("invalid-png", path.as_posix())
    return PngShape(
        width=width,
        height=height,
        row_bytes=row_bytes,
        bit_depth=bit_depth,
        color_type=color_type,
    )


def _decode_scanlines(compressed: bytes, shape: PngShape, path: Path) -> None:
    expected = shape.height * (shape.row_bytes + 1)
    try:
        inflater = zlib.decompressobj()
        decoded = inflater.decompress(compressed, expected + 1)
        if len(decoded) <= expected:
            decoded += inflater.flush(expected + 1 - len(decoded))
    except zlib.error as error:
        raise VisualQaError("invalid-png", path.as_posix()) from error
    if (
        len(decoded) != expected
        or not inflater.eof
        or inflater.unused_data
        or inflater.unconsumed_tail
    ):
        raise VisualQaError("invalid-png", path.as_posix())
    stride = shape.row_bytes + 1
    if any(decoded[offset] > 4 for offset in range(0, len(decoded), stride)):
        raise VisualQaError("invalid-png", path.as_posix())


def png_dimensions(encoded: bytes, path: Path) -> tuple[int, int]:
    """Validate all chunks, CRCs, IDAT decoding, IEND, and return dimensions."""
    if len(encoded) > MAX_ENCODED_BYTES or not encoded.startswith(types.PNG_SIGNATURE):
        raise VisualQaError("invalid-png", path.as_posix())
    offset = len(types.PNG_SIGNATURE)
    shape: PngShape | None = None
    idat: list[bytes] = []
    ended = False
    seen_plte = False
    idat_closed = False
    while offset < len(encoded):
        if ended or len(encoded) - offset < 12:
            raise VisualQaError("invalid-png", path.as_posix())
        length = struct.unpack(">I", encoded[offset : offset + 4])[0]
        chunk_end = offset + 12 + length
        if chunk_end > len(encoded):
            raise VisualQaError("invalid-png", path.as_posix())
        kind = encoded[offset + 4 : offset + 8]
        if len(kind) != 4 or any(
            byte not in range(ord("A"), ord("Z") + 1)
            and byte not in range(ord("a"), ord("z") + 1)
            for byte in kind
        ):
            raise VisualQaError("invalid-png", path.as_posix())
        data = encoded[offset + 8 : offset + 8 + length]
        declared_crc = struct.unpack(">I", encoded[offset + 8 + length : chunk_end])[0]
        if zlib.crc32(kind + data) & 0xFFFFFFFF != declared_crc:
            raise VisualQaError("invalid-png", path.as_posix())
        if kind == b"IHDR":
            if shape is not None or offset != len(types.PNG_SIGNATURE):
                raise VisualQaError("invalid-png", path.as_posix())
            shape = _shape(data, path)
        elif kind == b"IDAT":
            if (
                shape is None
                or ended
                or idat_closed
                or (shape.color_type == 3 and not seen_plte)
            ):
                raise VisualQaError("invalid-png", path.as_posix())
            idat.append(data)
        elif kind == b"PLTE":
            if (
                shape is None
                or idat
                or seen_plte
                or shape.color_type in {0, 4}
                or len(data) < 3
                or len(data) > 768
                or len(data) % 3 != 0
                or (shape.color_type == 3 and len(data) // 3 > 1 << shape.bit_depth)
            ):
                raise VisualQaError("invalid-png", path.as_posix())
            seen_plte = True
        elif kind == b"IEND":
            if length != 0 or shape is None or not idat:
                raise VisualQaError("invalid-png", path.as_posix())
            ended = True
        else:
            if kind[0] & 0x20 == 0:
                raise VisualQaError("invalid-png", path.as_posix())
            if idat:
                idat_closed = True
        offset = chunk_end
    if shape is None or not ended or offset != len(encoded):
        raise VisualQaError("invalid-png", path.as_posix())
    _decode_scanlines(b"".join(idat), shape, path)
    return shape.width, shape.height
