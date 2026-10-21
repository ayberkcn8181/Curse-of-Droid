"""Immutable publisher-reference requirements; never trust a saved 'verified' flag.

A manifest describes expected bytes and targets. It is a user-reviewed reference,
not a publisher signature. Full hashing happens before execution and each file use.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_MANIFEST = 64 * 1024
_DEVICE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_KINDS = {"rom", "recovery", "addon", "gsi"}


class ArtifactError(Exception):
    """Missing, invalid, changed or mismatched installation input."""


@dataclass(frozen=True)
class ArtifactManifest:
    filename: str
    kind: str
    size: int
    sha256: str
    source_url: str
    devices: tuple[str, ...]
    abi: str = ""
    layout: str = ""


@dataclass(frozen=True)
class ArtifactRequirement:
    path: Path
    manifest: ArtifactManifest
    identity: tuple[int, ...]


def manifest_path(path: Path) -> Path:
    return path.with_name(path.name + ".manifest.json")


def _identity(s: os.stat_result) -> tuple[int, ...]:
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _path_matches(s: os.stat_result, opened: tuple[int, ...]) -> bool:
    # Windows stat/lstat can expose creation time as ctime while fstat exposes
    # change time (CPython #157671). Compare ctime only within the same API.
    # Full handle identities, including ctime, are retained across file uses.
    return _identity(s)[:4] == opened[:4]


def _regular(path: Path) -> os.stat_result:
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode):
        raise ArtifactError("installation inputs must be regular files, not links or device paths")
    return s


def _open_regular(path: Path):
    # NONBLOCK prevents a concurrently substituted FIFO from blocking open().
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ArtifactError("installation input is no longer a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest field")
        result[key] = value
    return result


def _parse(document: dict, filename: str, kind: str) -> ArtifactManifest:
    required = {"version", "filename", "kind", "size", "sha256", "source_url", "devices"}
    if not isinstance(document, dict) or not required <= document.keys() or document.keys() - required - {"abi", "layout"}:
        raise ArtifactError("manifest fields are missing or unsupported")
    if type(document["version"]) is not int or document["version"] != 1:
        raise ArtifactError("unsupported artifact manifest version")
    if document["filename"] != filename or kind not in _KINDS or document["kind"] != kind:
        raise ArtifactError("manifest filename or artifact kind does not match the selected file")
    size, digest = document["size"], document["sha256"]
    if type(size) is not int or not 0 < size < 2**63:
        raise ArtifactError("manifest needs a positive byte size")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise ArtifactError("manifest needs a publisher-reference SHA-256 digest")
    source = document["source_url"]
    try:
        if not isinstance(source, str) or len(source) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in source):
            raise ValueError("invalid source")
        url = urlsplit(source)
        if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None or url.fragment:
            raise ValueError("invalid source")
        _ = url.port
    except ValueError:
        raise ArtifactError("manifest source must be an HTTPS reference without credentials or fragments") from None
    devices = document["devices"]
    if (not isinstance(devices, list) or not 1 <= len(devices) <= 32
            or any(not isinstance(d, str) or not _DEVICE.fullmatch(d) for d in devices)
            or len({d.lower() for d in devices}) != len(devices)):
        raise ArtifactError("manifest must name explicit, distinct device codenames")
    abi, layout = document.get("abi", ""), document.get("layout", "")
    if not isinstance(abi, str) or not isinstance(layout, str) or len(abi) > 64 or len(layout) > 64:
        raise ArtifactError("invalid manifest ABI/layout")
    if kind == "gsi" and (not abi or not layout):
        raise ArtifactError("GSI manifest must declare ABI and image layout")
    if kind != "gsi" and (abi or layout):
        raise ArtifactError("ABI/layout fields are only supported for GSI manifests")
    return ArtifactManifest(filename, kind, size, digest.lower(), source, tuple(devices), abi, layout)


def require_artifact(path: Path, kind: str) -> ArtifactRequirement:
    """Capture a bounded reference and file identity; this does not claim a hash check."""
    path = Path(path).absolute()
    reference = manifest_path(path)
    try:
        before = _regular(reference)
        if before.st_size > MAX_MANIFEST:
            raise ArtifactError("artifact manifest is too large")
        with _open_regular(reference) as stream:
            opened = _identity(os.fstat(stream.fileno()))
            if not _path_matches(before, opened):
                raise ArtifactError("artifact manifest changed before reading")
            raw = stream.read(MAX_MANIFEST + 1)
            if len(raw) > MAX_MANIFEST or _identity(os.fstat(stream.fileno())) != opened:
                raise ArtifactError("artifact manifest changed while reading")
        if _identity(_regular(reference)) != _identity(before):
            raise ArtifactError("artifact manifest changed while reading")
        manifest = _parse(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique), path.name, kind)
        before = _regular(path)
        canonical = path.resolve(strict=True)
        with _open_regular(canonical) as stream:
            opened = _identity(os.fstat(stream.fileno()))
            if not _path_matches(before, opened) or _identity(_regular(canonical)) != _identity(before):
                raise ArtifactError("installation input changed while planning")
            if opened[2] != manifest.size:
                raise ArtifactError(f"{path.name}: file size does not match the manifest")
        return ArtifactRequirement(canonical, manifest, opened)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise ArtifactError(f"{path.name}: need a readable file and valid {reference.name}; see docs/INSTALL_PREFLIGHT.md") from None


def verify_artifact(requirement: ArtifactRequirement) -> None:
    """Re-hash the current file against the captured reference, never a saved verdict."""
    path, manifest = requirement.path, requirement.manifest
    try:
        before = _regular(path)
        if not _path_matches(before, requirement.identity):
            raise ArtifactError(f"{path.name}: file changed since planning; create a new plan")
        digest, total = hashlib.sha256(), 0
        with _open_regular(path) as stream:
            if _identity(os.fstat(stream.fileno())) != requirement.identity:
                raise ArtifactError(f"{path.name}: file changed before verification")
            while block := stream.read(1 << 20):
                total += len(block)
                if total > manifest.size:
                    raise ArtifactError(f"{path.name}: file grew during verification")
                digest.update(block)
            if _identity(os.fstat(stream.fileno())) != requirement.identity:
                raise ArtifactError(f"{path.name}: file changed during verification")
        if _identity(_regular(path)) != _identity(before):
            raise ArtifactError(f"{path.name}: file was replaced during verification")
        if total != manifest.size or digest.hexdigest() != manifest.sha256:
            raise ArtifactError(f"{path.name}: SHA-256/size does not match the captured manifest")
    except OSError:
        raise ArtifactError(f"{path.name}: installation file is unavailable") from None
