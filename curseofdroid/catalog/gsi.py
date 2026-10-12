"""Generic System Images for Treble devices without an official ROM (TrebleDroid builds, GitHub releases).

A GSI replaces only the system partition and runs on the phone's own vendor partition, so whether it works
depends on the vendor implementation; the tool says so. TrebleDroid publishes no checksums, so only the size
reported by GitHub can be verified.
"""

from __future__ import annotations

import lzma
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..device.profile import DeviceProfile
from ..platform.net import fetch_json
from .base import Artifact, Build

RELEASES = "https://api.github.com/repos/TrebleDroid/treble_experimentations/releases?per_page=10"
_ASSET = re.compile(r"^system-td-(?P<arch>arm64|arm32_binder64)(?:-ab)?-(?P<flavour>vanilla|gapps|floss)"
                    r"(?P<old>-old)?\.img\.xz$")


@dataclass
class GsiFit:
    ok: bool
    arch: str = ""
    reasons: list[str] = field(default_factory=list)  # why not, or caveats


def gsi_fit(profile: DeviceProfile) -> GsiFit:
    reasons = []
    if profile.treble == "no":
        return GsiFit(False, reasons=["the phone isn't Treble-enabled, so a GSI can't run on its vendor"])
    if profile.treble == "unknown":
        reasons.append("Treble support couldn't be read (needs the phone in Android or recovery)")
    abi = profile.abi or ""
    arch = "arm64" if abi.startswith("arm64") else "arm32_binder64" if abi.startswith("armeabi") else ""
    if not arch:
        return GsiFit(False, reasons=[f"no GSI for CPU ABI '{abi or 'unknown'}'"])
    # Current TrebleDroid images are system-as-root ("ab") builds; A-only phones without system-as-root
    # (launched with Android 8.x) can't boot them. ro.build.system_root_image describes the device here.
    if profile.ab == "no" and profile.system_as_root == "no":
        return GsiFit(False, arch, ["current TrebleDroid GSIs need system-as-root; this A-only phone doesn't "
                                    "use it (phones launched with Android 8.x) — only older GSI generations "
                                    "or a ROM built for the device fit"])
    if profile.vndk_version and profile.vndk_version.isdigit() and int(profile.vndk_version) < 28:
        era = {"26": "8.0", "27": "8.1"}.get(profile.vndk_version, "8")
        reasons.append(f"the vendor is from Android {era} (VNDK {profile.vndk_version}); new GSIs often fail "
                       f"on vendors this old")
    if profile.bootloader_unlocked != "yes":
        reasons.append("the bootloader must be unlocked")
    return GsiFit(True, arch, reasons)


def trebledroid_builds(profile: DeviceProfile, fetch=fetch_json) -> list[Build]:
    fit = gsi_fit(profile)
    if not fit.ok:
        return []
    out = []
    for rel in fetch(RELEASES):
        for a in rel.get("assets", []):
            m = _ASSET.match(a["name"])
            if not m or m["arch"] != fit.arch:
                continue
            variant = m["flavour"] + (" (alternative '-old' build)" if m["old"] else "")
            out.append(Build("TrebleDroid GSI", "gsi", profile.codename, rel["tag_name"],
                             _date(rel.get("published_at")),
                             [Artifact(a["name"], a["browser_download_url"], a.get("size"))],
                             variant=variant, info_url=rel.get("html_url", ""),
                             notes=(rel.get("body") or "").strip()[:500]))
        if out:  # newest release that has an image for this architecture
            break
    out.sort(key=lambda b: "-old" in b.main.filename)  # the regular build first
    return out


def _date(iso):
    import datetime as dt
    try:
        return dt.date.fromisoformat((iso or "")[:10])
    except ValueError:
        return None


def unpack_xz(src: Path, dest: Path | None = None) -> Path:
    """GSIs are published as .img.xz; fastboot needs the raw image."""
    dest = dest or src.with_suffix("")  # foo.img.xz -> foo.img
    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return dest
    tmp = dest.with_name(dest.name + ".part")
    with lzma.open(src) as fin, open(tmp, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)
    tmp.replace(dest)
    return dest
