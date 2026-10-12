"""Look inside a ROM/recovery zip before it goes anywhere near the phone: which devices does it claim?"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

_ASSERT = re.compile(r'getprop\("ro\.(?:product\.)?(?:device|build\.product)"\)\s*==\s*"([^"]+)"')


@dataclass
class PackageInfo:
    path: Path
    kind: str  # "ota-zip" (recovery sideload), "image" (raw .img), "unknown"
    devices: list[str] = field(default_factory=list)  # empty = package doesn't say
    ab_payload: bool = False  # payload.bin (A/B / virtual A/B OTA)
    has_installer: bool = False  # META-INF/com/google/android/update-binary

    def matches(self, codenames: list[str]) -> bool | None:
        """True/False if the package names devices, None if it doesn't (caller must ask the user)."""
        if not self.devices:
            return None
        lower = {c.lower() for c in codenames}
        return any(d.lower() in lower for d in self.devices)


def inspect(path: Path) -> PackageInfo:
    if path.suffix.lower() == ".img":
        return PackageInfo(path, "image")
    if not zipfile.is_zipfile(path):
        return PackageInfo(path, "unknown")
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        info = PackageInfo(path, "ota-zip", ab_payload="payload.bin" in names,
                           has_installer="META-INF/com/google/android/update-binary" in names)
        devices: list[str] = []
        meta = "META-INF/com/android/metadata"
        if meta in names:
            for line in zf.read(meta).decode("utf-8", "replace").splitlines():
                if line.startswith("pre-device="):
                    devices += [d for d in line.split("=", 1)[1].split(",") if d]
        script = "META-INF/com/google/android/updater-script"
        if not devices and script in names:
            devices += _ASSERT.findall(zf.read(script).decode("utf-8", "replace"))
        info.devices = list(dict.fromkeys(devices))
        if not info.has_installer and not info.ab_payload:
            info.kind = "unknown"
        return info
