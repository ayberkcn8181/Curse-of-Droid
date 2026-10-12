"""adb: devices, properties. Read-only operations only in this module."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import Tool

_PROP_RE = re.compile(r"^\[(?P<key>[^\]]+)\]: \[(?P<val>.*)\]$")


@dataclass
class AdbDevice:
    serial: str
    state: str  # device, recovery, sideload, unauthorized, offline, bootloader
    info: dict[str, str]


def parse_devices(text: str) -> list[AdbDevice]:
    """Parse `adb devices -l`."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
        out.append(AdbDevice(parts[0], parts[1], info))
    return out


def parse_getprop(text: str) -> dict[str, str]:
    """Parse `adb shell getprop` output (`[key]: [value]`, values may be empty)."""
    props = {}
    for line in text.splitlines():
        if m := _PROP_RE.match(line.rstrip("\r")):
            props[m["key"]] = m["val"]
    return props


class Adb(Tool):
    def devices(self) -> list[AdbDevice]:
        return parse_devices(self.run("devices", "-l").stdout)

    def getprop(self) -> dict[str, str]:
        return parse_getprop(self.run("shell", "getprop").stdout)

    def shell(self, command: str, timeout: float = 30) -> str:
        return self.run("shell", command, timeout=timeout).stdout
