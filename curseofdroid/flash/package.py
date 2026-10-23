"""Bounded, cancellable ROM ZIP metadata inspection. Never extracts or executes entries."""
from __future__ import annotations

import io
import os
import re
import stat
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .artifacts import (ArtifactError, VerificationCancelled, _identity, _open_regular, _path_matches, _regular)

MAX_DIRECTORY = 8 * 1024 * 1024
MAX_ENTRIES = 50_000
MAX_NAME = 4096
MAX_METADATA = 512 * 1024  # per supported text entry; at most two are inspected
MAX_COMPRESSED_METADATA = 1024 * 1024
MAX_READ_TOTAL = 32 * 1024 * 1024
READ_CHUNK = 64 * 1024
META = "META-INF/com/android/metadata"
SCRIPT = "META-INF/com/google/android/updater-script"
INSTALLER = "META-INF/com/google/android/update-binary"
CRITICAL = {META, SCRIPT, INSTALLER, "payload.bin"}
FOLDED_CRITICAL = {n.lower() for n in CRITICAL}
_ASSERT = re.compile(r'getprop\("ro\.(?:product\.)?(?:device|build\.product)"\)\s*==\s*"([^"]+)"')
_DEVICE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


class PackageError(ArtifactError):
    """Unsupported, inconsistent or over-budget package metadata."""


@dataclass
class PackageInfo:
    path: Path
    kind: str  # ota-zip (markers only), image, unknown
    devices: list[str] = field(default_factory=list)
    ab_payload: bool = False
    has_installer: bool = False
    identity: tuple[int, ...] | None = None

    def matches(self, codenames: list[str]) -> bool | None:
        if not self.devices:
            return None
        lower = {c.lower() for c in codenames}
        return any(d.lower() in lower for d in self.devices)


class _Reader:
    """Limit every host read, including reads made by ZipFile itself after preflight."""
    def __init__(self, stream, identity, cancelled):
        self.stream, self.identity, self.cancelled = stream, identity, cancelled
        self.size, self.read_bytes = identity[2], 0

    def check(self):
        if self.cancelled and self.cancelled():
            raise VerificationCancelled("package inspection cancelled")
        if _identity(os.fstat(self.stream.fileno())) != self.identity:
            raise PackageError("package changed during inspection")

    def tell(self): return self.stream.tell()
    def seekable(self): return True

    def seek(self, offset, whence=io.SEEK_SET):
        self.check()
        position = offset + (self.tell() if whence == io.SEEK_CUR else self.size if whence == io.SEEK_END else 0)
        if whence not in {io.SEEK_SET, io.SEEK_CUR, io.SEEK_END} or not 0 <= position <= self.size:
            raise PackageError("ZIP offset is outside the captured file")
        return self.stream.seek(position)

    def read(self, size=-1):
        self.check()
        size = self.size - self.tell() if size is None or size < 0 else size
        if size > MAX_DIRECTORY or self.read_bytes + size > MAX_READ_TOTAL:
            raise PackageError("ZIP inspection read budget exceeded")
        data = self.stream.read(size)
        self.read_bytes += len(data)
        self.check()
        return data


def _directory(reader: _Reader) -> tuple[int, int, int]:
    """Validate classic/standard ZIP64 EOCD before ZipFile allocates its directory."""
    length = min(reader.size, 65535 + 22)
    reader.seek(reader.size - length)
    tail = reader.read(length)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise PackageError("ZIP end record is missing or truncated")
    _, disk, cd_disk, on_disk, count, size, offset, comment = struct.unpack_from("<4s4H2IH", tail, position)
    if position + 22 + comment != len(tail) or disk or cd_disk or on_disk != count:
        raise PackageError("ZIP end record is inconsistent, trailing or multi-disk")
    end = reader.size - length + position
    directory_end = end
    locator = b""
    if end >= 20:
        reader.seek(end - 20)
        locator = reader.read(20)
    if locator.startswith(b"PK\x06\x07"):
        _, zip_disk, zip_offset, disks = struct.unpack("<4sIQI", locator)
        # Standard fixed-size ZIP64 EOCD works consistently on all supported Pythons.
        if zip_disk or disks != 1 or zip_offset + 56 != end - 20:
            raise PackageError("unsupported ZIP64 locator or extensible end record")
        reader.seek(zip_offset)
        record = reader.read(56)
        if len(record) != 56:
            raise PackageError("truncated ZIP64 end record")
        sig, record_size, _, _, disk64, cd_disk64, on_disk64, count64, size64, offset64 = struct.unpack("<4sQ2H2I4Q", record)
        if sig != b"PK\x06\x06" or record_size != 44 or disk64 or cd_disk64 or on_disk64 != count64:
            raise PackageError("unsupported ZIP64 end record")
        if any(small not in {large, sentinel} for small, large, sentinel in (
            (on_disk, on_disk64, 0xFFFF), (count, count64, 0xFFFF),
            (size, size64, 0xFFFFFFFF), (offset, offset64, 0xFFFFFFFF))):
            raise PackageError("classic and ZIP64 directory fields disagree")
        count, size, offset, directory_end = count64, size64, offset64, zip_offset
    elif count == 0xFFFF or size == 0xFFFFFFFF or offset == 0xFFFFFFFF:
        raise PackageError("ZIP64 end records are required")
    if size > MAX_DIRECTORY or count > MAX_ENTRIES:
        raise PackageError("ZIP directory exceeds the 8 MiB / 50000 entry budget")
    if offset + size != directory_end or count * 46 > size or (not count and size):
        raise PackageError("ZIP directory offsets/counts are inconsistent; prefixed archives are unsupported")
    reader.seek(offset)
    data = reader.read(size)
    position = seen = 0
    while position < size:
        reader.check()
        if position + 46 > size or data[position:position+4] != b"PK\x01\x02":
            raise PackageError("invalid ZIP directory entry")
        name, extra, comment, disk = struct.unpack_from("<4H", data, position + 28)
        if not 0 < name <= MAX_NAME or disk:
            raise PackageError("ZIP entry name or disk is unsupported")
        position += 46 + name + extra + comment
        seen += 1
        if position > size or seen > count or seen > MAX_ENTRIES:
            raise PackageError("ZIP directory entry bounds/count disagree")
    if position != size or seen != count:
        raise PackageError("ZIP directory entry count does not match its end record")
    return offset, size, count


def _entries(archive, directory_offset, expected_count, reader):
    rows = archive.infolist()
    if len(rows) != expected_count or archive.start_dir != directory_offset:
        raise PackageError("ZIP reader disagrees with the bounded directory")
    names, offsets = set(), set()
    for entry in rows:
        reader.check()
        name = entry.filename
        parts = name.rstrip("/").split("/")
        if (len(name) > MAX_NAME or name != entry.orig_filename or name.startswith("/") or "\\" in name or ":" in name or "//" in name
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(part in {"", ".", ".."} for part in parts)):
            raise PackageError("ZIP entry name is ambiguous or non-canonical")
        if name in names or entry.header_offset in offsets:
            raise PackageError("duplicate ZIP entry name or local header")
        if not 0 <= entry.header_offset <= directory_offset - 30 or entry.volume:
            raise PackageError("ZIP local header is outside the data area")
        if entry.flag_bits & (1 | 0x40 | 0x2000):
            raise PackageError("encrypted ZIP entries are unsupported")
        if name.rstrip("/").lower() in FOLDED_CRITICAL:
            file_type = stat.S_IFMT(entry.external_attr >> 16) if entry.create_system == 3 else 0
            if name not in CRITICAL or entry.external_attr & 0x10 or file_type not in {0, stat.S_IFREG}:
                raise PackageError("critical ZIP entry is an alias, directory or special file")
        names.add(name)
        offsets.add(entry.header_offset)
    for name in (META, SCRIPT):
        if name in names:
            entry = archive.getinfo(name)
            if (entry.file_size > MAX_METADATA or entry.compress_size > MAX_COMPRESSED_METADATA
                    or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or entry.flag_bits & ~0x80E):
                raise PackageError("ZIP text metadata exceeds the size budget or uses unsupported compression/flags")
    if offsets and min(offsets) != 0:
        raise PackageError("prefixed or unreferenced initial ZIP data is unsupported")
    ordered = sorted(offsets) + [directory_offset]
    return names, dict(zip(ordered, ordered[1:]))


def _local_zip64(extra, uncompressed, compressed):
    position, found = 0, None
    while position < len(extra):
        if position + 4 > len(extra):
            raise PackageError("truncated ZIP local extra field")
        tag, size = struct.unpack_from("<2H", extra, position)
        position += 4
        if position + size > len(extra):
            raise PackageError("truncated ZIP local extra data")
        if tag == 1:
            if found is not None:
                raise PackageError("duplicate local ZIP64 extra field")
            found = extra[position:position+size]
        position += size
    cursor = 0
    values = []
    for value in (uncompressed, compressed):
        if value == 0xFFFFFFFF:
            if found is None or cursor + 8 > len(found):
                raise PackageError("local ZIP64 sizes are missing")
            value = struct.unpack_from("<Q", found, cursor)[0]
            cursor += 8
        values.append(value)
    return values


def _text(archive, name, reader, end_offset):
    """Decode the *whole* bounded compressed stream, including beyond claimed size.

    ZipExtFile stops at its declared file_size, which cannot establish that a
    forged smaller size hid further output. Deflate max_length always stays >0.
    """
    entry = archive.getinfo(name)
    reader.seek(entry.header_offset)
    raw = reader.read(30)
    if len(raw) != 30:
        raise PackageError("truncated ZIP local header")
    sig, _, flags, method, _, _, crc, compressed, expanded, name_size, extra_size = struct.unpack("<4s5H3I2H", raw)
    if (sig != b"PK\x03\x04" or flags != entry.flag_bits or method != entry.compress_type
            or not 0 < name_size <= MAX_NAME):
        raise PackageError("ZIP local header disagrees with its directory")
    local_name, extra = reader.read(name_size), reader.read(extra_size)
    expected_name = entry.orig_filename.encode("utf-8" if flags & 0x800 else "cp437")
    if local_name != expected_name or len(extra) != extra_size:
        raise PackageError("ZIP local name or extra data is inconsistent")
    expanded, compressed = _local_zip64(extra, expanded, compressed)
    if not flags & 8 and (crc, compressed, expanded) != (entry.CRC, entry.compress_size, entry.file_size):
        raise PackageError("ZIP local sizes/CRC disagree with the directory")
    if reader.tell() + entry.compress_size > end_offset:
        raise PackageError("ZIP text metadata overlaps another entry or its directory")
    blocks, done, crc = [], 0, 0
    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
    remaining = entry.compress_size
    while remaining:
        reader.check()
        data = reader.read(min(READ_CHUNK, remaining))
        if not data:
            raise PackageError("truncated ZIP text metadata")
        remaining -= len(data)
        while True:
            reader.check()
            limit = min(READ_CHUNK, min(entry.file_size, MAX_METADATA) + 1 - done)
            if limit <= 0:
                raise PackageError("ZIP text metadata expanded beyond its declared size/budget")
            output = decoder.decompress(data, limit) if decoder else data
            done += len(output)
            if done > entry.file_size or done > MAX_METADATA:
                raise PackageError("ZIP text metadata expanded beyond its declared size/budget")
            blocks.append(output)
            crc = zlib.crc32(output, crc)
            if not decoder:
                break
            if decoder.eof:
                if decoder.unused_data or decoder.unconsumed_tail or remaining:
                    raise PackageError("trailing bytes after the ZIP text deflate stream")
                break
            data = decoder.unconsumed_tail
            if not data and len(output) < limit:
                break
    if decoder and not decoder.eof:
        raise PackageError("truncated ZIP text deflate stream")
    if done != entry.file_size or crc != entry.CRC:
        raise PackageError("ZIP text metadata size/CRC is inconsistent")
    return b"".join(blocks).decode("utf-8")


def _inspect_zip(path, reader):
    directory, _, count = _directory(reader)
    if count == 0:
        # The validated empty directory has no members to classify. Older
        # Python ZIP64 probes seek before byte zero on this 22-byte archive.
        return PackageInfo(path, "unknown")
    reader.seek(0)
    with zipfile.ZipFile(reader) as archive:
        names, ends = _entries(archive, directory, count, reader)
        texts = {name: _text(archive, name, reader, ends[archive.getinfo(name).header_offset]) for name in (META, SCRIPT) if name in names}
        devices, declarations = [], 0
        for line in texts.get(META, "").splitlines():
            if line.startswith("pre-device="):
                declarations += 1
                devices += line.split("=", 1)[1].split(",")
        if declarations > 1:
            raise PackageError("duplicate pre-device declarations are ambiguous")
        if not devices:
            devices = _ASSERT.findall(texts.get(SCRIPT, ""))
        if len(devices) > 32 or any(not _DEVICE.fullmatch(d) for d in devices):
            raise PackageError("ZIP device declarations are malformed or exceed the target budget")
        info = PackageInfo(path, "ota-zip", list(dict.fromkeys(devices)),
                           "payload.bin" in names, INSTALLER in names)
        if not info.ab_payload and not info.has_installer:
            info.kind = "unknown"
        return info


def inspect(path: Path, *, cancelled: Callable[[], bool] | None = None) -> PackageInfo:
    """Inspect only bounded directory/text metadata; markers do not prove installability.

    The callback is checked around file reads and directory scanning. Cancellation
    cannot interrupt a blocked OS read or the bounded ZipFile constructor itself.
    """
    path = Path(path)
    if cancelled and cancelled():
        raise VerificationCancelled("package inspection cancelled")
    if path.suffix.lower() == ".img":
        return PackageInfo(path, "image")
    try:
        before = _regular(path)
        with _open_regular(path) as stream:
            opened = _identity(os.fstat(stream.fileno()))
            if not _path_matches(before, opened):
                raise PackageError("package changed before inspection")
            reader = _Reader(stream, opened, cancelled)
            signature = reader.read(4)
            if signature in {b"PK\x03\x04", b"PK\x05\x06", b"PK\x06\x06"}:
                info = _inspect_zip(path, reader)
            else:
                info = PackageInfo(path, "unknown")
            reader.check()
            info.identity = opened
            if (not _path_matches(_regular(path), opened)
                    or _identity(_regular(path)) != _identity(before)):
                raise PackageError("package was replaced during inspection")
            return info
    except (PackageError, VerificationCancelled):
        raise
    except (ArtifactError, OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError, UnicodeError, EOFError, struct.error, zlib.error):
        raise PackageError("package is unreadable or has malformed/unsupported ZIP metadata") from None
