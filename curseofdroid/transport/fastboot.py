"""fastboot: devices and variables. Read-only operations only in this module."""

from __future__ import annotations

import re

from .base import Tool

# `fastboot getvar all` prints to stderr as "(bootloader) key: value" or "key: value". Keys can contain colons
# ("partition-size:system: 0x..."), so the key ends at the first ": ".
_PREFIX = re.compile(r"^\(bootloader\)\s*")
_KEY_RE = re.compile(r"^[\w.\-:]+$")


def parse_devices(text: str) -> list[tuple[str, str]]:
    """Parse `fastboot devices` -> [(serial, mode)], mode is "fastboot" or "fastbootd"."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def parse_getvar_all(text: str) -> dict[str, str]:
    vars_: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Finished") or line.startswith("getvar:"):
            continue
        line = _PREFIX.sub("", line)
        key, sep, val = line.partition(": ")
        if not sep:  # "key:" with an empty value
            if line.endswith(":"):
                key, val = line[:-1], ""
            else:
                continue
        if not _KEY_RE.match(key):
            continue
        # partition-type:system, partition-size:system, is-logical:system stay as composite keys
        vars_[key] = val.strip()
    return vars_


class Fastboot(Tool):
    def devices(self) -> list[tuple[str, str]]:
        return parse_devices(self.read("devices").stdout)

    def getvar_all(self) -> dict[str, str]:
        r = self.read("getvar", "all", timeout=60)
        return parse_getvar_all(r.stderr + "\n" + r.stdout)

    def getvar(self, name: str) -> str | None:
        r = self.read("getvar", name)
        vars_ = parse_getvar_all(r.stderr + "\n" + r.stdout)
        return vars_.get(name)
