"""Bounded structural sizing of raw / Android sparse images. Never expands data."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

from .artifacts import ArtifactError, _open_regular

SPARSE_MAGIC = 0xED26FF3A
MAX_CHUNKS = 1_000_000
MAX_EXPANDED = (1 << 63) - 1


@dataclass(frozen=True)
class ImageExtent:
    file_bytes: int
    expanded_bytes: int
    sparse: bool


def image_extent(path: Path) -> ImageExtent:
    """Validate sparse chunk accounting and size; SHA-256 is checked separately.

    Format: AOSP system/core/libsparse/sparse_format.h. This is not a filesystem,
    boot header, image checksum or ABI validator.
    """
    try:
        with _open_regular(path) as stream:
            size = os.fstat(stream.fileno()).st_size
            if not 0 < size <= MAX_EXPANDED:
                raise ArtifactError("image size is empty or unsupported")
            header = stream.read(28)
            if len(header) < 4 or struct.unpack_from("<I", header)[0] != SPARSE_MAGIC:
                return ImageExtent(size, size, False)
            if len(header) != 28:
                raise ArtifactError("truncated Android sparse header")
            _, major, minor, file_header, chunk_header, block, blocks, chunks, _ = struct.unpack("<I4H4I", header)
            if (major != 1 or minor != 0 or not 28 <= file_header <= 4096
                    or not 12 <= chunk_header <= 4096 or not 0 < block <= 1 << 20 or block % 4
                    or not blocks or not 0 < chunks <= MAX_CHUNKS or blocks * block > MAX_EXPANDED):
                raise ArtifactError("unsupported Android sparse header or size budget")
            if file_header > size:
                raise ArtifactError("sparse header exceeds the file")
            stream.seek(file_header)
            output_blocks = 0
            for _ in range(chunks):
                position = stream.tell()
                raw = stream.read(chunk_header)
                if len(raw) != chunk_header:
                    raise ArtifactError("truncated sparse chunk header")
                kind, reserved, count, total = struct.unpack_from("<2H2I", raw)
                payload = total - chunk_header
                if reserved or payload < 0 or position + total > size:
                    raise ArtifactError("invalid sparse chunk bounds")
                if kind == 0xCAC1:
                    valid = count > 0 and payload == count * block
                elif kind == 0xCAC2:
                    valid = count > 0 and payload == 4
                elif kind == 0xCAC3:
                    valid = count > 0 and payload == 0
                elif kind == 0xCAC4:
                    valid = count == 0 and payload == 4
                else:
                    valid = False
                if not valid:
                    raise ArtifactError("unsupported or inconsistent sparse chunk")
                output_blocks += count
                if output_blocks > blocks:
                    raise ArtifactError("sparse chunks exceed the declared output size")
                stream.seek(payload, os.SEEK_CUR)
            if stream.tell() != size or output_blocks != blocks:
                raise ArtifactError("sparse image has trailing data or inconsistent output blocks")
            return ImageExtent(size, blocks * block, True)
    except OSError:
        raise ArtifactError("image is unavailable for capacity validation") from None
