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
    market_name: str = ""  # "OPPO Reno15 F 5G" — what people call the phone
    soc: str = ""
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
    virtual_ab: Tristate = "unknown"
    boot_partitions: list[str] = field(default_factory=list)  # init_boot / vendor_boot when the device has them
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


# Marketing name properties used by different vendors
_MARKET_NAME_PROPS = ("ro.product.marketname", "ro.product.vendor.marketname", "ro.vendor.oplus.market.name",
                      "ro.config.marketing_name", "ro.product.odm.marketname", "ro.vendor.product.display")


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
    unlocked = _unlocked_from_props(props)
    # ro.boot.slot_suffix comes from the bootloader. ro.build.ab_update describes the *system image* and is
    # "true" on A-only phones running an A/B-built GSI, so it is only a fallback.
    if g("ro.boot.slot_suffix"):
        ab = "yes"
    elif g("ro.build.version.sdk"):  # full property set from a running OS/recovery: no slot suffix = A-only
        ab = "no"
    else:
        ab = "unknown"
    return DeviceProfile(
        mode=mode,
        serial=serial or g("ro.serialno", ""),
        brand=g("ro.product.brand", "") or g("ro.product.system.brand", ""),
        manufacturer=g("ro.product.manufacturer", "") or g("ro.product.vendor.manufacturer", ""),
        model=g("ro.product.model", "") or g("ro.product.vendor.model", ""),
        market_name=next((g(k) for k in _MARKET_NAME_PROPS if g(k)), ""),
        soc=" ".join(x for x in (g("ro.soc.manufacturer"), g("ro.soc.model")) if x),
        # vendor/odm values describe the hardware even under a GSI; ro.product.device may be the ROM's name
        # ro.product.board / ro.board.platform are SoC platform names (msm8937, parrot), never device codenames:
        # looking them up could match an unrelated phone
        codenames=_codenames(g("ro.product.vendor.device"), g("ro.product.odm.device"), g("ro.product.device"),
                             g("ro.build.product"), g("ro.lineage.device")),
        android_version=g("ro.build.version.release", ""),
        sdk=int(sdk) if sdk and sdk.isdigit() else None,
        security_patch=g("ro.build.version.security_patch", ""),
        fingerprint=g("ro.build.fingerprint", "") or g("ro.system.build.fingerprint", ""),
        abi=g("ro.product.cpu.abi", ""),
        bootloader_unlocked=unlocked,
        oem_unlock_allowed=_yesno(g("sys.oem_unlock_allowed")),
        verified_boot_state=g("ro.boot.verifiedbootstate", ""),
        ab=ab,
        current_slot=(g("ro.boot.slot_suffix") or "").lstrip("_"),
        dynamic_partitions=_yesno(g("ro.boot.dynamic_partitions")),
        virtual_ab=_yesno(g("ro.virtual_ab.enabled")),
        boot_partitions=[p for p in ("init_boot", "vendor_boot")
                         if p in (g("ro.product.ab_ota_partitions") or "").split(",")],
        treble=_yesno(g("ro.treble.enabled")),
        vndk_version=g("ro.vndk.version", ""),
        system_as_root=_yesno(g("ro.build.system_root_image")),
        sources=["getprop"],
    )


def _unlocked_from_props(props: dict[str, str]) -> Tristate:
    """Best guess from properties; fastboot (getvar unlocked / oem lock-state) is authoritative."""
    g = props.get
    # Huawei/Honor: the bootloader passes "locked"/"green" to the kernel even when unlocked; ro.userlock is right
    if g("ro.userlock") in ("unlocked", "locked"):
        return "yes" if g("ro.userlock") == "unlocked" else "no"
    if g("ro.boot.vbmeta.device_state") in ("unlocked", "locked"):
        return "yes" if g("ro.boot.vbmeta.device_state") == "unlocked" else "no"
    if g("ro.boot.flash.locked") is not None:
        return {"yes": "no", "no": "yes", "unknown": "unknown"}[_yesno(g("ro.boot.flash.locked"))]
    vb = g("ro.boot.verifiedbootstate", "")
    if vb:  # green = locked stock, yellow = locked custom key, orange = unlocked
        return "yes" if vb == "orange" else "no"
    return "unknown"


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
