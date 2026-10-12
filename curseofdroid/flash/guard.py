"""The last line of defence: every adb/fastboot command a plan runs is checked here first.

Writes are only allowed to partitions an OS or recovery installation needs. Firmware partitions (bootloader,
modem, persist, EFS, ...) can brick a phone or destroy its IMEI/calibration and are never written. Relocking the
bootloader is never done automatically: relocking with a non-stock OS bricks many devices.
"""

from __future__ import annotations

import re
from typing import Sequence

# Partitions an install may write (with or without _a/_b slot suffix).
ALLOWED_WRITE = {
    "boot", "init_boot", "vendor_boot", "recovery", "dtbo", "vbmeta", "vbmeta_system", "vbmeta_vendor",
    "system", "system_ext", "product", "vendor", "odm", "vendor_dlkm", "odm_dlkm", "system_dlkm",
    "super", "userdata", "metadata", "cache",
    # A-only Huawei/Treble-era names
    "kernel", "ramdisk", "recovery_ramdisk", "recovery_vendor",
}
# Logical partitions (inside super) may only be written in fastbootd.
LOGICAL = {"system", "system_ext", "product", "vendor", "odm", "vendor_dlkm", "odm_dlkm", "system_dlkm"}
# Named so the refusal can say why; anything not in ALLOWED_WRITE is refused anyway.
FIRMWARE_EXAMPLES = {
    "abl", "xbl", "xbl_config", "aboot", "sbl1", "tz", "hyp", "rpm", "keymaster", "cmnlib", "cmnlib64",
    "devcfg", "modem", "radio", "bluetooth", "dsp", "persist", "modemst1", "modemst2", "fsg", "fsc", "efs",
    "nvram", "nvdata", "protect1", "protect2", "seccfg", "lk", "preloader", "oeminfo", "nvme", "fastboot",
    "xloader", "frp", "misc", "devinfo", "splash", "logo", "param", "sec_efs", "bootloader", "uefi",
}
_SUFFIX = re.compile(r"_(a|b)$")

_NEVER = [("flashing", "lock"), ("oem", "lock"), ("oem", "relock"), ("flashing", "lock_critical"),
          ("flashing", "unlock_critical")]


class GuardError(Exception):
    pass


def base_name(partition: str) -> str:
    return _SUFFIX.sub("", partition)


def check_partition(partition: str, *, fastbootd: bool = False) -> None:
    name = base_name(partition)
    if name not in ALLOWED_WRITE:
        why = "firmware partition" if name in FIRMWARE_EXAMPLES else "not on the install allowlist"
        raise GuardError(f"refusing to write '{partition}': {why}")
    if name in LOGICAL and not fastbootd:
        # On dynamic-partition devices these live inside super and must be flashed from fastbootd. Legacy
        # devices have real partitions with these names: their plans pass logical_ok=True.
        raise GuardError(f"'{partition}' is a logical partition here: flash it from fastbootd")


# fastboot commands a plan may use. Everything else (vendor "oem" commands, flashall, update, ...) is refused.
_FASTBOOT_READ = {"getvar", "devices", "reboot", "reboot-bootloader", "reboot-recovery", "reboot-fastboot",
                  "continue", "boot"}
_FASTBOOT_WRITE = {"flash", "erase", "format", "-w", "set_active", "--set-active"}
# Unlocking wipes the phone and is only issued by a vendor module after its own confirmation (allow_unlock).
_UNLOCK = {("flashing", "unlock"), ("oem", "unlock"), ("flashing", "get_unlock_ability"),
           ("oem", "get_unlock_data"), ("oem", "device-info")}
_WIPEABLE = {"userdata", "metadata", "cache"}


def check_command(tool: str, args: Sequence[str], *, fastbootd: bool = False, logical_ok: bool = False,
                  allow_unlock: bool = False) -> None:
    """Raise GuardError unless the command is safe for an install plan."""
    a = [x for x in args if x]
    while a and a[0] in ("-s", "-t"):  # global options with a value
        a = a[2:]
    low = [x.lower() for x in a]
    for pair in _NEVER:
        if tuple(low[:2]) == pair:
            raise GuardError(f"refusing '{' '.join(a)}': relocking/critical-lock changes are never automated")
    if tool == "fastboot":
        if any(x in ("--disable-verity", "--disable-verification") for x in low):
            raise GuardError("refusing to disable verified boot flags without a ROM-specific override")
        if not low:
            raise GuardError("empty fastboot command")
        if tuple(low[:2]) in _UNLOCK:
            if not allow_unlock:
                raise GuardError(f"'{' '.join(a)}' is only allowed from a vendor unlock flow")
            return
        # skip leading options such as --slot=all / --skip-reboot
        i = 0
        while i < len(low) and low[i].startswith("--") and not low[i].startswith("--set-active"):
            i += 1
        if i == len(low):
            raise GuardError("fastboot command without a sub-command")
        cmd = "--set-active" if low[i].startswith("--set-active") else low[i].split(":")[0]  # format:ext4
        if cmd in ("flashall", "update"):
            raise GuardError(f"refusing 'fastboot {cmd}': it writes every image in a set, including firmware")
        if cmd in _FASTBOOT_READ or cmd in ("set_active", "--set-active"):
            return
        if cmd == "-w":
            return  # wipes userdata (+cache) only
        if cmd not in _FASTBOOT_WRITE:
            raise GuardError(f"refusing unknown fastboot command '{low[i]}'")
        rest = [x for x in a[i + 1:] if not x.startswith("-")]
        if not rest:
            raise GuardError(f"'fastboot {cmd}' without a partition")
        part = rest[0]
        if cmd in ("erase", "format") and base_name(part) not in _WIPEABLE:
            raise GuardError(f"refusing to {cmd} '{part}': only userdata/metadata/cache may be wiped")
        check_partition(part, fastbootd=fastbootd or logical_ok)
    elif tool == "adb":
        joined = " ".join(low)
        # raw block writes from a recovery shell are allowed only to a named, allowlisted by-name partition
        if re.search(r"\bdd\b.*\bof=", joined):
            m = re.search(r"of=/dev/block/(?:bootdevice/|platform/[^ ]+/)?by-name/([\w]+)", joined)
            if not m:
                raise GuardError("refusing raw 'dd' to a device path that isn't a by-name partition")
            check_partition(m.group(1), fastbootd=True)  # a real block device, not a logical one
        if re.search(r"\b(mkfs\.\w+|make_ext4fs|mke2fs)\b", joined):
            m = re.search(r"by-name/(\w+)", joined)
            if not m or base_name(m.group(1)) not in {"userdata", "metadata", "cache"}:
                raise GuardError("refusing to format anything but userdata/metadata/cache")
    else:
        raise GuardError(f"unknown tool {tool}")
