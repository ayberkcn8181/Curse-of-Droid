"""HTTP helpers: JSON/text fetch with a small on-disk cache, and verified resumable downloads."""

from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .. import __version__
from .paths import data_dir

USER_AGENT = f"curseofdroid/{__version__} (+https://github.com/)"
CACHE_SECONDS = 24 * 3600


def ssl_context() -> ssl.SSLContext:
    """CA certificates from certifi when available.

    A frozen (PyInstaller) Python looks for the CA store at the path of the machine it was built on, which
    doesn't exist on the user's machine — every HTTPS request then fails with CERTIFICATE_VERIFY_FAILED.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


class NotFound(Exception):
    pass


def _request(url: str, headers: dict | None = None) -> urllib.request.Request:
    h = {"User-Agent": USER_AGENT}
    h.update(headers or {})
    return urllib.request.Request(url, headers=h)


def fetch_text(url: str, cache: bool = True, timeout: float = 30) -> str:
    """GET a small text resource; raises NotFound on 404. Cached for a day."""
    path = data_dir() / "cache" / hashlib.sha256(url.encode()).hexdigest()
    if cache and path.is_file() and time.time() - path.stat().st_mtime < CACHE_SECONDS:
        text = path.read_text(encoding="utf-8")
        if text == "\0404":
            raise NotFound(url)
        return text
    try:
        with urlopen(_request(url), timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            if cache:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\0404", encoding="utf-8")
            raise NotFound(url) from None
        raise
    if cache:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return text


def fetch_json(url: str, cache: bool = True):
    return json.loads(fetch_text(url, cache))


Fetcher = Callable[[str], str]


class VerificationError(Exception):
    pass


def download(url: str, dest: Path, *, size: int | None = None, hashes: dict[str, str] | None = None,
             headers: dict | None = None, progress: Callable[[int, int | None], None] | None = None) -> Path:
    """Download to dest (resuming a partial dest.part) and verify size and hashes before renaming into place."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = _request(url, headers)
    if have:
        req.add_header("Range", f"bytes={have}-")
    with urlopen(req, 60) as resp:
        mode = "ab" if have and resp.status == 206 else "wb"
        done = have if mode == "ab" else 0
        with open(part, mode) as f:
            while chunk := resp.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, size)
    verify(part, size=size, hashes=hashes)
    part.replace(dest)
    return dest


def verify(path: Path, *, size: int | None = None, hashes: dict[str, str] | None = None) -> None:
    if size is not None and path.stat().st_size != size:
        raise VerificationError(f"{path.name}: size {path.stat().st_size}, expected {size}")
    for algo, expected in (hashes or {}).items():
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
        if h.hexdigest().lower() != expected.lower():
            raise VerificationError(f"{path.name}: {algo} mismatch")
