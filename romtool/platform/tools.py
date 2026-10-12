"""Locate adb/fastboot, or install Google's platform-tools into romtool's data directory."""

from __future__ import annotations

import io
import shutil
import stat
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .paths import tools_dir

PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-{os}.zip"
_OS_NAMES = {"win32": "windows", "darwin": "darwin"}


def platform_tools_os() -> str:
    return _OS_NAMES.get(sys.platform, "linux")


def _exe(name: str) -> str:
    return name + ".exe" if sys.platform == "win32" else name


@dataclass
class Tools:
    adb: Path | None
    fastboot: Path | None
    source: str  # "romtool", "PATH" or "missing"

    @property
    def complete(self) -> bool:
        return self.adb is not None and self.fastboot is not None


def find_tools() -> Tools:
    """Prefer romtool's own platform-tools (known version), then whatever is on PATH."""
    own = tools_dir() / "platform-tools"
    adb, fastboot = own / _exe("adb"), own / _exe("fastboot")
    if adb.is_file() and fastboot.is_file():
        return Tools(adb, fastboot, "romtool")
    on_path = shutil.which("adb"), shutil.which("fastboot")
    if all(on_path):
        return Tools(Path(on_path[0]), Path(on_path[1]), "PATH")
    return Tools(None, None, "missing")


def install_platform_tools(url: str | None = None) -> Tools:
    """Download platform-tools over HTTPS from Google and unpack it into the tools directory.

    Google does not publish a checksum for the "latest" archive; the zip's own CRCs are checked on extraction
    (zipfile raises on a corrupt member) and the download is HTTPS from dl.google.com only.
    """
    url = url or PLATFORM_TOOLS_URL.format(os=platform_tools_os())
    if not url.startswith("https://dl.google.com/"):
        raise ValueError(f"refusing to download platform-tools from {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    dest = tools_dir()
    target = dest / "platform-tools"
    staging = dest / "platform-tools.new"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if bad := zf.testzip():
            raise IOError(f"corrupt member in platform-tools archive: {bad}")
        zf.extractall(staging)
    # the archive contains a top-level platform-tools/ directory
    shutil.rmtree(target, ignore_errors=True)
    (staging / "platform-tools").rename(target)
    shutil.rmtree(staging, ignore_errors=True)
    if sys.platform != "win32":
        for name in ("adb", "fastboot"):
            p = target / name
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return find_tools()
