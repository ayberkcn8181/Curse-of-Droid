"""Bounded ZIP inspection on real local bytes, never a device or extracted file."""
import io
import os
import stat
import struct
import threading
import warnings
import zipfile
import zlib

import pytest

from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash import package
from curseofdroid.flash.artifacts import VerificationCancelled
from curseofdroid.flash.package import PackageError, inspect
from curseofdroid.flash.planner import InstallRequest, PlanError, plan_sideload_install


META, SCRIPT, INSTALLER = package.META, package.SCRIPT, package.INSTALLER


def build(path, entries=None, compression=zipfile.ZIP_DEFLATED, comment=b"", force64=False):
    entries = entries if entries is not None else {"payload.bin": b"unread payload", META: b"pre-device=lavender\n"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=compression) as archive:
            for name, value in (entries.items() if isinstance(entries, dict) else entries):
                if force64:
                    with archive.open(name, "w", force_zip64=True) as member:
                        member.write(value)
                else:
                    archive.writestr(name, value)
            archive.comment = comment
    return path


def records(data):
    end = data.rfind(b"PK\x05\x06")
    fields = struct.unpack_from("<4s4H2IH", data, end)
    offset, size = fields[6], fields[5]
    items, at = [], offset
    while at < offset + size:
        name, extra, comment = struct.unpack_from("<3H", data, at + 28)
        text = bytes(data[at+46:at+46+name]).decode("utf-8")
        local = struct.unpack_from("<I", data, at + 42)[0]
        items.append((text, at, local))
        at += 46 + name + extra + comment
    return end, items


def mutate(path, callback):
    data = bytearray(path.read_bytes())
    end, items = records(data)
    callback(data, end, items)
    path.write_bytes(data)


def zip64(path):
    data = path.read_bytes()
    end, _ = records(data)
    sig, disk, cd_disk, on_disk, count, size, offset, comment = struct.unpack_from("<4s4H2IH", data, end)
    record = struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    locator = struct.pack("<4sIQI", b"PK\x06\x07", 0, end, 1)
    classic = struct.pack("<4s4H2IH", sig, disk, cd_disk, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, comment)
    path.write_bytes(data[:end] + record + locator + classic + data[end+22:])
    return path


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("force64", [False, True])
def test_supported_metadata_and_local_zip64_are_read_without_payload(tmp_path, compression, force64, monkeypatch):
    path = build(tmp_path / "rom.zip", compression=compression, force64=force64,
                 comment=b"ordinary OTA signature/comment bytes")
    # No extraction, payload decompression or unbounded ZipFile.read is permitted.
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda *_: pytest.fail("unbounded member read"))
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *_a, **_k: pytest.fail("metadata decoder must remain bounded"))
    info = inspect(path)
    assert info.kind == "ota-zip" and info.devices == ["lavender"] and info.ab_payload and info.identity


def test_standard_zip64_end_records_and_comment(tmp_path):
    path = zip64(build(tmp_path / "zip64.zip", comment=b"whole-file signature placeholder"))
    assert inspect(path).devices == ["lavender"]


def test_legacy_script_and_no_embedded_target_remain_supported(tmp_path):
    path = build(tmp_path / "legacy.zip", {INSTALLER: b"unread executable", SCRIPT:
        b'assert(getprop("ro.product.device") == "lavender");'})
    assert inspect(path).devices == ["lavender"] and inspect(path).has_installer
    build(path, {INSTALLER: b"not executed"})
    assert inspect(path).matches(["lavender"]) is None


@pytest.mark.parametrize("data", [b"", b"not a package", b"self-extracting prefixPK\x03\x04"])
def test_non_zip_inputs_are_unknown_not_executed(tmp_path, data):
    path = tmp_path / "other.bin"
    path.write_bytes(data)
    assert inspect(path).kind == "unknown"


def test_empty_valid_zip_and_image_classification(tmp_path):
    assert inspect(build(tmp_path / "empty.zip", {})).kind == "unknown"
    assert inspect(tmp_path / "not-opened.img").kind == "image"


@pytest.mark.parametrize("change", ["directory-size", "entry-count", "offset", "disk", "count-mismatch", "trailing", "truncated", "name-size", "entry-disk", "signature"])
def test_directory_rejections_happen_before_zipfile_allocation(tmp_path, monkeypatch, change):
    path = build(tmp_path / "bad.zip")
    def patch(data, end, items):
        if change == "directory-size": struct.pack_into("<I", data, end+12, package.MAX_DIRECTORY+1)
        elif change == "entry-count": struct.pack_into("<2H", data, end+8, package.MAX_ENTRIES+1, package.MAX_ENTRIES+1)
        elif change == "offset": struct.pack_into("<I", data, end+16, 0)
        elif change == "disk": struct.pack_into("<H", data, end+4, 1)
        elif change == "count-mismatch": struct.pack_into("<2H", data, end+8, 1, 1)
        elif change == "trailing": data.extend(b"trailing")
        elif change == "truncated": del data[end:]
        elif change == "name-size": struct.pack_into("<H", data, items[0][1]+28, package.MAX_NAME+1)
        elif change == "entry-disk": struct.pack_into("<H", data, items[0][1]+34, 1)
        else: data[items[0][1]:items[0][1]+4] = b"NOPE"
    mutate(path, patch)
    monkeypatch.setattr(zipfile, "ZipFile", lambda *_a, **_k: pytest.fail("over-budget/invalid directory reached ZipFile"))
    with pytest.raises(PackageError): inspect(path)


@pytest.mark.parametrize("change", ["locator-disk", "locator-count", "locator-offset", "record-size", "record-disk", "record-count", "size-budget", "classic-conflict", "signature"])
def test_zip64_end_records_are_strict_and_bounded(tmp_path, change):
    path = zip64(build(tmp_path / "bad64.zip"))
    data = bytearray(path.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    record = end - 20 - 56
    if change == "locator-disk": struct.pack_into("<I", data, end-16, 1)
    elif change == "locator-count": struct.pack_into("<I", data, end-4, 2)
    elif change == "locator-offset": struct.pack_into("<Q", data, end-12, record-1)
    elif change == "record-size": struct.pack_into("<Q", data, record+4, 45)
    elif change == "record-disk": struct.pack_into("<I", data, record+16, 1)
    elif change == "record-count": struct.pack_into("<Q", data, record+32, package.MAX_ENTRIES+1)
    elif change == "size-budget": struct.pack_into("<Q", data, record+40, package.MAX_DIRECTORY+1)
    elif change == "classic-conflict": struct.pack_into("<2H", data, end+8, 1, 1)
    else: data[record:record+4] = b"NOPE"
    path.write_bytes(data)
    with pytest.raises(PackageError): inspect(path)


@pytest.mark.parametrize("name", ["payload.bin/", "PAYLOAD.BIN", "../payload.bin", "/payload.bin", "./payload.bin", "a//b", "a/../b", "a\\b", "C:payload.bin", "bad\x01name", "bad\x7fname", "dir//"])
def test_ambiguous_or_noncanonical_names_are_rejected(tmp_path, name):
    path = build(tmp_path / "bad-name.zip", [("payload.bin", b"x"), (name, b"x")])
    with pytest.raises(PackageError): inspect(path)


@pytest.mark.parametrize("name", ["payload.bin", META, SCRIPT, "other"])
def test_duplicate_names_are_not_silently_overwritten(tmp_path, name):
    path = build(tmp_path / "duplicate.zip", [(name, b"a"), (name, b"b")])
    with pytest.raises(PackageError, match="duplicate"): inspect(path)


@pytest.mark.parametrize("kind", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFDIR])
def test_critical_entries_must_be_regular_files(tmp_path, kind):
    item = zipfile.ZipInfo("payload.bin")
    item.create_system = 3
    item.external_attr = (kind | 0o644) << 16
    path = build(tmp_path / "special.zip", [(item, b"unread")])
    with pytest.raises(PackageError, match="special"): inspect(path)


@pytest.mark.parametrize("flag", [1, 0x40, 0x2000])
def test_encryption_flags_are_not_accepted(tmp_path, flag):
    path = build(tmp_path / "encrypted.zip")
    mutate(path, lambda data, _e, rows: struct.pack_into("<H", data, rows[0][1]+8, flag))
    with pytest.raises(PackageError, match="encrypted"): inspect(path)


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_metadata_exactly_at_budget_is_supported(tmp_path, compression):
    text = b"pre-device=lavender\n#" + b"x" * (package.MAX_METADATA - 21)
    assert len(text) == package.MAX_METADATA
    path = build(tmp_path / "boundary.zip", {"payload.bin": b"x", META: text}, compression)
    assert inspect(path).devices == ["lavender"]


@pytest.mark.parametrize("name", [META, SCRIPT])
def test_compressed_bomb_is_rejected_without_decompression(tmp_path, monkeypatch, name):
    path = build(tmp_path / "bomb.zip", {"payload.bin": b"x", name: b"x" * (package.MAX_METADATA+1)})
    monkeypatch.setattr(zlib, "decompressobj", lambda *_: pytest.fail("oversized declared metadata was decompressed"))
    with pytest.raises(PackageError, match="size budget"): inspect(path)


@pytest.mark.parametrize("method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_metadata_decoder_memory_cannot_be_selected_by_archive(tmp_path, method):
    path = build(tmp_path / "method.zip", compression=method)
    with pytest.raises(PackageError, match="unsupported compression"): inspect(path)


@pytest.mark.parametrize("fault", ["smaller-size", "larger-size", "bad-crc", "local-name", "local-flags", "local-compression", "trailing-deflate", "truncated-deflate"])
def test_entire_metadata_stream_and_local_header_must_agree(tmp_path, fault):
    path = build(tmp_path / "stream.zip", {META: b"pre-device=lavender\n" * 5, "payload.bin": b"x"})
    def patch(data, _end, rows):
        _, cd, local = next(r for r in rows if r[0] == META)
        if fault in {"smaller-size", "larger-size"}:
            actual = struct.unpack_from("<I", data, cd+24)[0]
            fake = 1 if fault == "smaller-size" else actual+1
            struct.pack_into("<I", data, cd+24, fake)
            struct.pack_into("<I", data, local+22, fake)
            # A CRC of only the forged prefix must not authorize unconsumed output.
            if fault == "smaller-size":
                crc = zlib.crc32(b"p")
                struct.pack_into("<I", data, cd+16, crc)
                struct.pack_into("<I", data, local+14, crc)
        elif fault == "bad-crc":
            struct.pack_into("<I", data, cd+16, 0)
            struct.pack_into("<I", data, local+14, 0)
        elif fault == "local-name": data[local+30] = ord("X")
        elif fault == "local-flags": struct.pack_into("<H", data, local+6, 8)
        elif fault == "local-compression": struct.pack_into("<H", data, local+8, zipfile.ZIP_STORED)
        else:
            size = struct.unpack_from("<I", data, cd+20)[0] + (1 if fault == "trailing-deflate" else -1)
            struct.pack_into("<I", data, cd+20, size)
            struct.pack_into("<I", data, local+18, size)
    mutate(path, patch)
    with pytest.raises(PackageError): inspect(path)


@pytest.mark.parametrize("text", [b"pre-device=lavender\npre-device=oriole\n", b"pre-device=\n", b"pre-device=lavender,\n", b"pre-device=../x\n", b"pre-device=" + b"x"*129, b"pre-device=" + b",".join([b"x"]*33), b"\xff"])
def test_device_declarations_are_bounded_and_unambiguous(tmp_path, text):
    path = build(tmp_path / "declarations.zip", {"payload.bin": b"x", META: text})
    with pytest.raises(PackageError): inspect(path)


def test_read_wrapper_caps_single_and_cumulative_reads(tmp_path, monkeypatch):
    path = tmp_path / "bytes"
    path.write_bytes(b"a" * 32)
    with path.open("rb") as stream:
        reader = package._Reader(stream, package._identity(os.fstat(stream.fileno())), None)
        monkeypatch.setattr(package, "MAX_DIRECTORY", 8)
        monkeypatch.setattr(package, "MAX_READ_TOTAL", 12)
        with pytest.raises(PackageError, match="budget"): reader.read()
        assert reader.read(8) == b"a" * 8
        with pytest.raises(PackageError, match="budget"): reader.read(8)
        with pytest.raises(PackageError, match="offset"): reader.seek(-1)


def test_directory_count_checks_actual_entries_not_only_declared_count(tmp_path):
    path = build(tmp_path / "fake-count.zip")
    mutate(path, lambda data, end, _r: struct.pack_into("<2H", data, end+8, 0, 0))
    with pytest.raises(PackageError): inspect(path)


def test_cancellation_before_open_and_during_directory_scan(tmp_path):
    with pytest.raises(VerificationCancelled): inspect(tmp_path / "missing.zip", cancelled=lambda: True)
    path = build(tmp_path / "many.zip", {f"entry-{i}": b"x" for i in range(50)})
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 15
    with pytest.raises(VerificationCancelled): inspect(path, cancelled=cancelled)


def test_cancellation_between_actual_metadata_chunks(tmp_path, monkeypatch):
    text = b"#" + b"x" * (3 * package.READ_CHUNK)
    path = build(tmp_path / "cancel.zip", {"payload.bin": b"x", META: text}, zipfile.ZIP_STORED)
    cancel = threading.Event()
    original = package._Reader.read
    def read(reader, size=-1):
        data = original(reader, size)
        if size == package.READ_CHUNK and data.startswith(b"#"): cancel.set()
        return data
    monkeypatch.setattr(package._Reader, "read", read)
    with pytest.raises(VerificationCancelled): inspect(path, cancelled=cancel.is_set)


@pytest.mark.parametrize("action", ["edit", "replace"])
def test_file_edit_or_replacement_during_inspection_is_refused(tmp_path, monkeypatch, action):
    path = build(tmp_path / "changed.zip")
    original = package._entries
    def change_file(*args):
        result = original(*args)
        if action == "replace":
            other = path.with_name("other.zip")
            other.write_bytes(path.read_bytes())
            try:
                os.replace(other, path)
                return result
            except PermissionError:
                # Windows may deny replacement of the open handle: an in-place
                # size change must still stop before a result is returned.
                pass
        with path.open("ab") as output:
            output.write(b"changed")
        return result
    monkeypatch.setattr(package, "_entries", change_file)
    with pytest.raises(PackageError, match="changed|replaced"): inspect(path)


def test_stale_package_metadata_cannot_be_bound_to_a_new_manifest(tmp_path, artifact_manifest):
    path = build(tmp_path / "rom.zip")
    info = inspect(path)
    build(path, {"payload.bin": b"a different payload", META: b"pre-device=lavender\n"})
    artifact_manifest(path)
    profile = DeviceProfile(serial="S1", codenames=["lavender"], bootloader_unlocked="yes", ab="no")
    with pytest.raises(PlanError, match="changed since metadata inspection"):
        plan_sideload_install(profile, InstallRequest(info))


def test_missing_metadata_inspection_identity_is_not_authorization(tmp_path, artifact_manifest):
    path = build(tmp_path / "rom.zip")
    info = inspect(path)
    info.identity = None
    artifact_manifest(path)
    profile = DeviceProfile(serial="S1", codenames=["lavender"], bootloader_unlocked="yes", ab="no")
    with pytest.raises(PlanError, match="metadata inspection"):
        plan_sideload_install(profile, InstallRequest(info))


def test_large_zip64_directory_offset_uses_bounded_seeks_not_a_payload_read(tmp_path):
    original = build(tmp_path / "source.zip").read_bytes()
    end, _ = records(original)
    fields = struct.unpack_from("<4s4H2IH", original, end)
    count, size, old_offset = fields[4], fields[5], fields[6]
    offset = (1 << 32) + 4096
    zip64_offset = offset + size
    tail = original[old_offset:end]
    tail += struct.pack("<4sQ2H2I4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset)
    tail += struct.pack("<4sIQI", b"PK\x06\x07", 0, zip64_offset, 1)
    tail += struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    segments = [(0, original[:old_offset]), (offset, tail)]
    class SparseReader:
        # A virtual sparse byte source avoids a physical 4-GiB allocation on Windows.
        size = offset + len(tail)
        position = 0
        read_bytes = 0
        def check(self): pass
        def seekable(self): return True
        def tell(self): return self.position
        def seek(self, value, whence=0):
            self.position = value + (self.position if whence == 1 else self.size if whence == 2 else 0)
            assert 0 <= self.position <= self.size
            return self.position
        def read(self, length=-1):
            length = self.size-self.position if length < 0 else min(length, self.size-self.position)
            assert 0 <= length <= package.MAX_DIRECTORY
            output = bytearray(length)
            for start, value in segments:
                left, right = max(start,self.position), min(start+len(value),self.position+length)
                if left < right:
                    output[left-self.position:right-self.position] = value[left-start:right-start]
            self.position += length
            self.read_bytes += length
            return bytes(output)
    reader = SparseReader()
    info = package._inspect_zip(tmp_path / "virtual.zip", reader)
    assert info.devices == ["lavender"] and reader.read_bytes < 200_000


def test_streaming_writer_data_descriptors_are_supported(tmp_path):
    class NoSeek(io.BytesIO):
        def seek(self, *args): raise OSError("streaming output")
    output = NoSeek()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.bin", b"unread")
        archive.writestr(META, b"pre-device=lavender\n")
    path = tmp_path / "descriptor.zip"
    path.write_bytes(output.getvalue())
    assert inspect(path).devices == ["lavender"]


def test_addon_metadata_identity_is_also_required(tmp_path, artifact_manifest):
    rom = build(tmp_path / "rom.zip")
    addon = build(tmp_path / "addon.zip")
    artifact_manifest(rom)
    artifact_manifest(addon, "addon")
    info = inspect(addon)
    info.identity = None
    profile = DeviceProfile(serial="S1", codenames=["lavender"], bootloader_unlocked="yes", ab="no")
    with pytest.raises(PlanError, match="add-on package changed"):
        plan_sideload_install(profile, InstallRequest(inspect(rom), extras=(info,)))


@pytest.mark.parametrize("change", ["compressed-size", "duplicate-header", "bad-local-crc", "local-extra", "missing-local64"])
def test_additional_size_header_and_local_extra_conflicts(tmp_path, change):
    path = build(tmp_path / "fields.zip", force64=change in {"local-extra", "missing-local64"})
    def patch(data, _end, rows):
        _, cd, local = next(r for r in rows if r[0] == META)
        if change == "compressed-size": struct.pack_into("<I", data, cd+20, package.MAX_COMPRESSED_METADATA+1)
        elif change == "duplicate-header": struct.pack_into("<I", data, cd+42, rows[0][2])
        elif change == "bad-local-crc": struct.pack_into("<I", data, local+14, 0)
        else:
            name_size = struct.unpack_from("<H", data, local+26)[0]
            extra = local + 30 + name_size
            struct.pack_into("<H", data, extra+(2 if change == "local-extra" else 0), 0xFFFF)
    mutate(path, patch)
    with pytest.raises(PackageError): inspect(path)


def test_duplicate_local_zip64_extra_tags_are_rejected(tmp_path):
    info = zipfile.ZipInfo(META)
    info.extra = struct.pack("<2H", 1, 0) * 2
    path = build(tmp_path / "duplicate-extra.zip", [(info, b"pre-device=lavender\n"), ("payload.bin", b"x")])
    with pytest.raises(PackageError): inspect(path)


def test_nul_in_raw_zip_name_is_not_a_payload_alias(tmp_path):
    path = build(tmp_path / "nul.zip", {"payload.binXjunk": b"x"})
    def patch(data, _end, rows):
        _, cd, local = rows[0]
        data[cd+46+len("payload.bin")] = 0
        data[local+30+len("payload.bin")] = 0
    mutate(path, patch)
    with pytest.raises(PackageError, match="ambiguous"): inspect(path)


@pytest.mark.parametrize("flag", [0x10, 0x20, 0x4000, 0x8000])
def test_unsupported_metadata_flags_cannot_bypass_standard_reader_checks(tmp_path, flag):
    path = build(tmp_path / "flags.zip")
    def patch(data, _end, rows):
        _, cd, local = next(r for r in rows if r[0] == META)
        struct.pack_into("<H", data, cd+8, flag)
        struct.pack_into("<H", data, local+6, flag)
    mutate(path, patch)
    with pytest.raises(PackageError, match="unsupported compression/flags"): inspect(path)
