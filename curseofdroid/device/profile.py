"""DeviceProfile: what curseofdroid knows about the connected phone, built from getprop or fastboot variables."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Mode = Literal["android", "recovery", "sideload", "fastboot", "fastbootd", "unknown"]
Tristate = Literal["yes", "no", "unknown"]


def _yesno(value: str | None, yes=("1", "true", "yes"), no=("0", "false", "no")) -> Tristate:
    if value is None:
        return "unknown"
    v = value.strip().lower()
    if v in yes:
        return "yes"
    if v in no:
        return "no"
    return "unknown"


@dataclass
class DeviceProfile:
    mode: Mode = "unknown"
    serial: str = ""
    brand: str = ""
    manufacturer: str = ""
    model: str = ""
    codenames: list[str] = field(default_factory=list)  # most specific first, deduplicated
    android_version: str = ""
    sdk: int | None = None
    security_patch: str = ""
    fingerprint: str = ""
    abi: str = ""
    bootloader_unlocked: Tristate = "unknown"
    oem_unlock_allowed: Tristate = "unknown"
    verified_boot_state: str = ""  # green / yellow / orange / red
    ab: Tristate = "unknown"
    current_slot: str = ""
    dynamic_partitions: Tristate = "unknown"
    treble: Tristate = "unknown"
    vndk_version: str = ""
    system_as_root: Tristate = "unknown"
    battery_percent: int | None = None
    sources: list[str] = field(default_factory=list)

    @property
    def codename(self) -> str:
        return self.codenames[0] if self.codenames else ""

    def to_dict(self, redact: bool = True) -> dict:
        d = asdict(self)
        d["codename"] = self.codename
        if redact and d["serial"]:
            d["serial"] = d["serial"][:2] + "…" + d["serial"][-2:] if len(d["serial"]) > 4 else "…"
        return d

    def merge(self, other: "DeviceProfile") -> "DeviceProfile":
        """Fill unknown/empty fields from another profile (e.g. fastboot data after adb data)."""
        for name, value in asdict(other).items():
            mine = getattr(self, name)
            if name == "codenames":
                for c in value:
                    if c not in self.codenames:
                        self.codenames.append(c)
            elif name == "sources":
                self.sources += [s for s in value if s not in self.sources]
            elif mine in ("", None, "unknown") and value not in ("", None, "unknown"):
                setattr(self, name, value)
        return self


def _codenames(*candidates: str | None) -> list[str]:
    out: list[str] = []
    for c in candidates:
        if c:
            c = c.strip()
            if c and c not in out:
                out.append(c)
    return out


def from_props(props: dict[str, str], mode: Mode = "android", serial: str = "") -> DeviceProfile:
    """Build a profile from `getprop` (Android or a recovery such as TWRP)."""
    g = props.get
    sdk = g("ro.build.version.sdk")
    locked = g("ro.boot.flash.locked")
    vbstate = g("ro.boot.verifiedbootstate", "")
    if locked is not None:
        unlocked = {"yes": "no", "no": "yes", "unknown": "unknown"}[_yesno(locked)]
    elif vbstate:
        # green = stock and locked, yellow = locked with a custom key, orange = unlocked
        unlocked = "yes" if vbstate == "orange" else "no"
    elif g("ro.boot.vbmeta.device_state"):
        unlocked = "yes" if g("ro.boot.vbmeta.device_state") == "unlocked" else "no"
    else:
        unlocked = "unknown"
    ab = g("ro.build.ab_update")
    return DeviceProfile(
        mode=mode,
        serial=serial or g("ro.serialno", ""),
        brand=g("ro.product.brand", "") or g("ro.product.system.brand", ""),
        manufacturer=g("ro.product.manufacturer", "") or g("ro.product.vendor.manufacturer", ""),
        model=g("ro.product.model", "") or g("ro.product.vendor.model", ""),
        # vendor/odm values describe the hardware even under a GSI; ro.product.device may be the ROM's name
        codenames=_codenames(g("ro.product.vendor.device"), g("ro.product.odm.device"), g("ro.product.device"),
                             g("ro.build.product"), g("ro.product.board"), g("ro.lineage.device")),
        android_version=g("ro.build.version.release", ""),
        sdk=int(sdk) if sdk and sdk.isdigit() else None,
        security_patch=g("ro.build.version.security_patch", ""),
        fingerprint=g("ro.build.fingerprint", "") or g("ro.system.build.fingerprint", ""),
        abi=g("ro.product.cpu.abi", ""),
        bootloader_unlocked=unlocked,
        oem_unlock_allowed=_yesno(g("sys.oem_unlock_allowed")),
        verified_boot_state=vbstate,
        ab=_yesno(ab) if ab is not None else ("yes" if g("ro.boot.slot_suffix") else "unknown"),
        current_slot=(g("ro.boot.slot_suffix") or "").lstrip("_"),
        dynamic_partitions=_yesno(g("ro.boot.dynamic_partitions")),
        treble=_yesno(g("ro.treble.enabled")),
        vndk_version=g("ro.vndk.version", ""),
        system_as_root=_yesno(g("ro.build.system_root_image")),
        sources=["getprop"],
    )


def from_fastboot(vars_: dict[str, str], mode: Mode = "fastboot", serial: str = "") -> DeviceProfile:
    """Build a profile from `fastboot getvar all`."""
    g = vars_.get
    slot_count = g("slot-count")
    unlocked = _yesno(g("unlocked"))
    if unlocked == "unknown" and g("device-state"):
        unlocked = "yes" if g("device-state") == "unlocked" else "no"
    if mode == "fastboot" and _yesno(g("is-userspace")) == "yes":
        mode = "fastbootd"
    has_super = (any(k.startswith("is-logical:") for k in vars_) or g("super-partition-name") is not None
                 or "partition-size:super" in vars_)
    return DeviceProfile(
        mode=mode,
        serial=serial or g("serialno", ""),
        codenames=_codenames(g("product")),
        bootloader_unlocked=unlocked,
        ab=("yes" if slot_count and slot_count.isdigit() and int(slot_count) > 1
            else "no" if slot_count is not None else "unknown"),
        current_slot=g("current-slot", ""),
        dynamic_partitions="yes" if has_super else "unknown",
        battery_percent=_battery(g("battery-soc-ok"), g("battery-level")),
        sources=["fastboot getvar"],
    )


def _battery(_ok: str | None, level: str | None) -> int | None:
    if level and level.rstrip("%").isdigit():
        return int(level.rstrip("%"))
    return None
