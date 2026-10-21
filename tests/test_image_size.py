"""Sparse extent tests use tiny on-disk payloads; no decompression/allocation."""
import struct

import pytest

from curseofdroid.flash.artifacts import ArtifactError
from curseofdroid.flash.image_size import MAX_CHUNKS, SPARSE_MAGIC, image_extent


def header(blocks=1, chunks=1, **kw):
    values = dict(magic=SPARSE_MAGIC, major=1, minor=0, file_header=28, chunk_header=12,
                  block=4096, blocks=blocks, chunks=chunks, checksum=0)
    values.update(kw)
    return struct.pack("<I4H4I", *values.values())


def chunk(kind=0xCAC3, blocks=1, payload=b"", **kw):
    return struct.pack("<2H2I", kind, kw.get("reserved", 0), blocks,
                       kw.get("total", 12 + len(payload))) + payload


def test_raw_and_sparse_expanded_sizes(tmp_path):
    path = tmp_path / "image.img"
    path.write_bytes(b"controlled raw bytes")
    raw = image_extent(path)
    assert raw.file_bytes == raw.expanded_bytes == 20 and not raw.sparse
    data = header(4, 4) + chunk(0xCAC1, 1, b"a" * 4096) + chunk(0xCAC2, 1, b"b" * 4)
    data += chunk(0xCAC3, 2) + chunk(0xCAC4, 0, b"\0" * 4)
    path.write_bytes(data)
    sparse = image_extent(path)
    assert sparse.file_bytes == len(data) and sparse.expanded_bytes == 16384 and sparse.sparse


def test_large_sparse_extent_does_not_expand_or_allocate(tmp_path):
    path = tmp_path / "huge.img"
    path.write_bytes(header(0xFFFFFFFF) + chunk(blocks=0xFFFFFFFF))
    assert path.stat().st_size == 40
    assert image_extent(path).expanded_bytes == 0xFFFFFFFF * 4096


BAD_IMAGES = [
    b"", struct.pack("<I", SPARSE_MAGIC), header(major=2) + chunk(), header(minor=1) + chunk(),
    header(file_header=27) + chunk(), header(file_header=4097) + chunk(),
    header(file_header=100) + chunk(), header(chunk_header=11) + chunk(),
    header(chunk_header=4097) + chunk(), header(block=0) + chunk(), header(block=3) + chunk(),
    header(block=1 << 21) + chunk(), header(blocks=0) + chunk(), header(chunks=0) + chunk(),
    header(chunks=MAX_CHUNKS + 1) + chunk(), header() + chunk(reserved=1),
    header() + chunk(total=11), header() + chunk(total=100), header() + chunk(0xCAFF),
    header() + chunk(0xCAC1, 1, b"x"), header() + chunk(0xCAC2, 1, b"123"),
    header() + chunk(0xCAC3, 1, b"x"), header() + chunk(0xCAC4, 1, b"1234"),
    header() + chunk(0xCAC4, 0, b"123"), header() + chunk(blocks=0),
    header() + chunk(blocks=2), header(blocks=2) + chunk(), header() + chunk() + b"trailing",
    header(chunks=2) + chunk(), header() + b"\0" * 11,
]


@pytest.mark.parametrize("data", BAD_IMAGES, ids=[f"malformed-{i}" for i in range(len(BAD_IMAGES))])
def test_malformed_sparse_and_empty_images_fail_closed(tmp_path, data):
    path = tmp_path / "bad.img"
    path.write_bytes(data)
    with pytest.raises(ArtifactError):
        image_extent(path)


def test_extended_headers_are_accounted_for(tmp_path):
    path = tmp_path / "extended.img"
    path.write_bytes(header(file_header=32, chunk_header=16) + b"pad!"
                     + struct.pack("<2H2I", 0xCAC3, 0, 1, 16) + b"pad!")
    assert image_extent(path).expanded_bytes == 4096


def test_missing_image_is_a_preflight_error(tmp_path):
    with pytest.raises(ArtifactError):
        image_extent(tmp_path / "missing.img")
