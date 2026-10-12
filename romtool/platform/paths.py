"""Per-user data directories (tools, downloads, logs) on Windows, macOS and Linux."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "romtool"


def data_dir() -> Path:
    """Where romtool keeps platform-tools, downloads and caches. ROMTOOL_HOME overrides it."""
    if env := os.environ.get("ROMTOOL_HOME"):
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP


def tools_dir() -> Path:
    return data_dir() / "tools"


def downloads_dir() -> Path:
    return data_dir() / "downloads"


def logs_dir() -> Path:
    return data_dir() / "logs"
