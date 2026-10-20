"""HTTP helpers: JSON/text fetch with a small on-disk cache, and verified resumable downloads."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .. import __version__
from .paths import data_dir

USER_AGENT = f"curseofdroid/{__version__} (+https://github.com/)"
CACHE_SECONDS = 24 * 3600


def ssl_context() -> ssl.SSLContext:
    """Use certifi plus the host's trusted certificate authorities.

    A frozen (PyInstaller) Python looks for the CA store at the path of the machine it was built on, which
    doesn't exist on the user's machine — every HTTPS request then fails with CERTIFICATE_VERIFY_FAILED.
    """
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_default_certs()
        return context
    except ImportError:
        return ssl.create_default_context()


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if req.type == "https" and urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise VerificationError("Refusing an HTTPS redirect to an insecure URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urlopen(req, timeout: float):
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_context()), _HTTPSRedirect())
    return opener.open(req, timeout=timeout)


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


def fetch_bytes(url: str, cache_days: float = 1, timeout: float = 120) -> bytes:
    """GET a (larger) binary resource, cached on disk for cache_days."""
    path = data_dir() / "cache" / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
    if path.is_file() and time.time() - path.stat().st_mtime < cache_days * 86400:
        return path.read_bytes()
    try:
        with urlopen(_request(url), timeout) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from None
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def fetch_json(url: str, cache: bool = True):
    return json.loads(fetch_text(url, cache))


Fetcher = Callable[[str], str]


class VerificationError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


_HASH_LENGTHS = {"sha256": 64, "sha512": 128, "sha1": 40, "md5": 32}


def _verification_inputs(size, hashes):
    if size is not None and (type(size) is not int or size < 0):
        raise VerificationError("Invalid expected file size")
    for algo, value in (hashes or {}).items():
        if algo not in _HASH_LENGTHS or not isinstance(value, str) or not re.fullmatch(
                r"[0-9a-fA-F]{%d}" % _HASH_LENGTHS[algo], value):
            raise VerificationError("Invalid or unsupported publisher checksum")


def verification_label(*, size=None, hashes=None) -> str:
    """Describe checks that succeeded, without claiming authenticity or installation compatibility."""
    if hashes:
        strong = any(a in hashes for a in ("sha256", "sha512"))
        return ("Publisher checksum matched" if strong else "Legacy checksum matched (weak)") + ": " + ", ".join(sorted(hashes))
    return "Size checked; no publisher checksum" if size is not None else "Downloaded; no publisher checksum or expected size"


def download_destination(root: Path, codename: str, filename: str) -> Path:
    """Validate provider-controlled path components on every supported OS."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", codename):
        raise VerificationError("Invalid device codename in download path")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()+ -]{0,199}", filename)
            or filename.endswith((".", " ")) or filename.split(".")[0].upper() in
            {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
        raise VerificationError("Unsafe publisher filename")
    root = root.resolve()
    destination = root / codename / filename
    if not destination.resolve().is_relative_to(root):
        raise VerificationError("Download path escapes the downloads directory")
    return destination


def _check_cancel(cancelled):
    if cancelled and cancelled():
        raise DownloadCancelled("Download cancelled; partial bytes retained")


def _length(value):
    if value is None:
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise VerificationError("Invalid Content-Length")
    return int(value)


def download(url: str, dest: Path, *, size: int | None = None, hashes: dict[str, str] | None = None,
             headers: dict | None = None, progress: Callable[[int, int | None], None] | None = None,
             cancelled: Callable[[], bool] | None = None, phase: Callable[[str], None] | None = None) -> Path:
    """Resume only a matching strong-ETag response; verify before atomic promotion.

    Old partials without a matching sidecar restart from zero. Cancellation is cooperative between
    reads (the network timeout is 60 seconds) and during hashing. No automatic retry or TLS bypass.
    """
    _verification_inputs(size, hashes)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise VerificationError("Downloads require an HTTPS URL without credentials")
    _check_cancel(cancelled)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    meta = part.with_name(part.name + ".json")
    if any(p.is_symlink() for p in (dest, part, meta)):
        raise VerificationError("Refusing a symlink download destination")
    # Header values may contain private tokens; persist only their fingerprint.
    identity = dict(url=url, size=size, hashes=hashes or {},
                    headers=hashlib.sha256(json.dumps(headers or {}, sort_keys=True).encode()).hexdigest())
    try:
        saved = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    etag = saved.get("etag", "") if isinstance(saved, dict) and saved.get("identity") == identity else ""
    strong_etag = isinstance(etag, str) and re.fullmatch(r'"[\x21\x23-\x7e\x80-\xff]*"', etag)
    have = part.stat().st_size if part.is_file() and strong_etag else 0
    request_headers = dict(headers or {})
    # Callers cannot override integrity-related range/encoding controls.
    request_headers = {k: v for k, v in request_headers.items() if k.lower() not in {"range", "if-range", "accept-encoding"}}
    request_headers["Accept-Encoding"] = "identity"
    req = _request(url, request_headers)
    if have:
        req.add_header("Range", f"bytes={have}-")
        req.add_header("If-Range", etag)
    if phase:
        phase("downloading")
    try:
        response = urlopen(req, 60)
    except urllib.error.HTTPError as error:
        if error.code != 416 or not have:
            raise
        error.close()
        have = 0  # Complete/stale partial: one fresh request, never promote from 416 alone.
        response = urlopen(_request(url, request_headers), 60)
    with response as resp:
        _check_cancel(cancelled)
        if urllib.parse.urlsplit(resp.geturl()).scheme.lower() != "https":
            raise VerificationError("Download response is not HTTPS")
        if resp.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise VerificationError("Encoded download responses are unsupported")
        length = _length(resp.headers.get("Content-Length"))
        response_etag = resp.headers.get("ETag", "")
        if resp.status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", resp.headers.get("Content-Range", ""))
            if not have or not match or response_etag != etag or saved.get("final_url") != resp.geturl():
                raise VerificationError("Invalid resume range or changed ETag")
            first, last, total = map(int, match.groups())
            if first != have or last != total - 1 or last < first or (length is not None and length != last - first + 1):
                raise VerificationError("Resume does not match the saved partial")
            length = total - have
        elif resp.status == 200:
            have, total = 0, length
        else:
            raise VerificationError(f"Unexpected download status: {resp.status}")
        if size is not None and total is not None and total != size:
            raise VerificationError("Response size differs from publisher metadata")
        expected = size if size is not None else total
        if expected is not None and expected - have > shutil.disk_usage(dest.parent).free:
            raise VerificationError("Insufficient disk space for download")
        saved = dict(identity=identity, etag=response_etag, final_url=resp.geturl())
        done = have
        mode = "ab" if have else "wb"
        with open(part, mode) as f:
            # Truncate an old representation before giving its sidecar a new identity.
            meta.write_text(json.dumps(saved), encoding="utf-8")
            if progress:
                progress(done, expected)
            while True:
                _check_cancel(cancelled)
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                _check_cancel(cancelled)
                if expected is not None and done + len(chunk) > expected:
                    raise VerificationError("Response exceeds expected file size")
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, expected)
        if length is not None and done - have != length:
            raise VerificationError("Truncated download response")
    _check_cancel(cancelled)
    if phase:
        phase("verifying")
    try:
        verify(part, size=size, hashes=hashes, cancelled=cancelled)
    except VerificationError:
        meta.unlink(missing_ok=True)  # Never resume a file whose checksum already failed.
        raise
    _check_cancel(cancelled)
    part.replace(dest)
    meta.unlink(missing_ok=True)
    return dest


def verify(path: Path, *, size: int | None = None, hashes: dict[str, str] | None = None,
           cancelled: Callable[[], bool] | None = None) -> None:
    _verification_inputs(size, hashes)
    _check_cancel(cancelled)
    if size is not None and path.stat().st_size != size:
        raise VerificationError(f"{path.name}: size {path.stat().st_size}, expected {size}")
    digest = {algo: hashlib.new(algo) for algo in (hashes or {})}
    if digest:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                _check_cancel(cancelled)
                for h in digest.values():
                    h.update(chunk)
    for algo, h in digest.items():
        if h.hexdigest().lower() != hashes[algo].lower():
            raise VerificationError(f"{path.name}: {algo} mismatch")
