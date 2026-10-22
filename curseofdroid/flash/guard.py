"""The last line of defence: every adb/fastboot command a plan runs is checked here first.

Writes are only allowed to partitions an OS or recovery installation needs. Firmware partitions (bootloader,
modem, persist, EFS, ...) can brick a phone or destroy its IMEI/calibration and are never written. Relocking the
bootloader is never done automatically: relocking with a non-stock OS bricks many devices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FileUse:
    path: str
    operation: str
    partition: str = ""


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


# Plan commands use a deliberately small grammar. In particular, adb shell is not a
# plan primitive: shell operators, redirections and vendor commands are not parsed here.
# Device discovery has separate read-only transport probes.
_UNLOCK = {("flashing", "unlock"), ("oem", "unlock"), ("flashing", "get_unlock_ability"),
           ("oem", "get_unlock_data"), ("oem", "device-info")}
_WIPEABLE = {"userdata", "metadata", "cache"}
_REBOOT_TARGETS = {"bootloader", "recovery", "fastboot"}
_SERIAL = re.compile(r"[A-Za-z0-9_.:\[\]-]{1,256}")
_VARIABLE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}")
_UNLOCK_CODE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}")


def _arguments(tool: str, args: Sequence[str]) -> list[str]:
    if isinstance(args, (str, bytes)) or not isinstance(args, Sequence):
        raise GuardError("command arguments must be a sequence of strings")
    a = list(args)
    if any(not isinstance(x, str) or not x or any(ord(c) < 32 or ord(c) == 127 for c in x) for x in a):
        raise GuardError("empty, non-string or control-character command argument")
    # A single, explicit device selector may precede the command. Never discard
    # empty tokens or let a missing selector value consume a command/option.
    if a and a[0] in ("-s", "-t"):
        selector = a[0]
        if len(a) < 2:
            raise GuardError("device selector requires a value")
        if selector == "-t":
            if tool != "adb" or not re.fullmatch(r"[1-9][0-9]*", a[1]):
                raise GuardError("invalid adb transport ID")
        elif not _SERIAL.fullmatch(a[1]) or a[1].startswith("-"):
            raise GuardError("invalid device serial")
        a = a[2:]
        if a and a[0] in ("-s", "-t"):
            raise GuardError("duplicate device selector")
    if not a:
        raise GuardError(f"empty {tool} command")
    return a


def _arity(a: list[str], count: int) -> None:
    if len(a) != count:
        raise GuardError(f"'{a[0]}' expects {count - 1} argument(s); extra commands/options are refused")


def _file_operand(value: str) -> None:
    # These are host filenames passed as one argv element, never shell text.
    # Existence, content and device compatibility belong to artifact preflight.
    if value.startswith("-") or not value.strip():
        raise GuardError("image/package filename must not be an option or blank")


def _fastboot_options(a: list[str]) -> tuple[list[str], set[str]]:
    seen: set[str] = set()
    while a and (a[0] in ("--slot", "--skip-reboot") or a[0].startswith("--slot=")):
        option = a[0].split("=", 1)[0]
        if option in seen:
            raise GuardError(f"duplicate fastboot option '{option}'")
        seen.add(option)
        if option == "--slot":
            if a[0] == "--slot":
                if len(a) < 2:
                    raise GuardError("--slot requires a value")
                value, a = a[1], a[2:]
            else:
                value, a = a[0].split("=", 1)[1], a[1:]
            if value not in {"a", "b", "all"}:
                raise GuardError("slot must be a, b or all")
        else:
            a = a[1:]
    if not a:
        raise GuardError("fastboot command without a sub-command")
    return a, seen


def command_operation(tool: str, args: Sequence[str]) -> str:
    """Extract the operation from an already guard-validated command vector."""
    body = _arguments(tool, args)
    if tool == "fastboot":
        body, _ = _fastboot_options(body)
    return body[0].split(":", 1)[0]


def _check_adb(a: list[str]) -> FileUse | None:
    cmd = a[0]
    if cmd == "reboot":
        if len(a) == 1 or (len(a) == 2 and a[1] in _REBOOT_TARGETS):
            return
        raise GuardError("adb reboot accepts only bootloader, recovery or fastboot")
    if cmd == "sideload":
        _arity(a, 2)
        _file_operand(a[1])
        return FileUse(a[1], "sideload")
    if a in (["devices"], ["devices", "-l"], ["get-state"], ["get-serialno"]):
        return
    raise GuardError(f"refusing unknown adb plan command '{cmd}'; shell commands are not allowed")


def _check_fastboot(a: list[str], *, fastbootd: bool, logical_ok: bool, allow_unlock: bool,
                    allow_unlock_placeholder: bool) -> FileUse | None:
    if any(x.lower().split("=", 1)[0] in {"--disable-verity", "--disable-verification"} for x in a):
        raise GuardError("refusing to disable verified boot flags without a ROM-specific override")
    a, options = _fastboot_options(a)
    low_pair = tuple(x.lower() for x in a[:2])
    if low_pair in _NEVER:
        raise GuardError("relocking/critical-lock changes are never automated")

    cmd = a[0]
    pair = tuple(a[:2])
    if pair in _UNLOCK:
        if not allow_unlock:
            raise GuardError("command is only allowed from a vendor unlock flow")
        if options:
            raise GuardError("fastboot options are not allowed on a vendor unlock command")
        if pair == ("oem", "unlock") and len(a) == 3:
            code = a[2]
            if not _UNLOCK_CODE.fullmatch(code) and not (allow_unlock_placeholder and code == "{answer}"):
                raise GuardError("invalid vendor unlock code")
        else:
            _arity(a, 2)
        return

    if cmd in ("flashall", "update"):
        raise GuardError(f"refusing 'fastboot {cmd}': it writes every image in a set, including firmware")
    # Modifiers only apply to the explicitly supported write commands.
    if options and cmd not in {"flash", "erase", "format", "format:ext4", "format:f2fs", "-w"}:
        raise GuardError("fastboot options are only allowed on supported partition writes")
    if cmd == "devices":
        if a not in (["devices"], ["devices", "-l"]):
            raise GuardError("fastboot devices accepts only an optional -l")
    elif cmd == "getvar":
        _arity(a, 2)
        if not _VARIABLE.fullmatch(a[1]):
            raise GuardError("invalid fastboot variable name")
    elif cmd == "reboot":
        if len(a) != 1 and not (len(a) == 2 and a[1] in _REBOOT_TARGETS):
            raise GuardError("fastboot reboot accepts only bootloader, recovery or fastboot")
    elif cmd in {"reboot-bootloader", "reboot-recovery", "reboot-fastboot", "continue", "-w"}:
        _arity(a, 1)
    elif cmd == "boot":
        _arity(a, 2)
        _file_operand(a[1])
        return FileUse(a[1], "boot")
    elif cmd in {"set_active", "--set-active"}:
        _arity(a, 2)
        if a[1] not in {"a", "b"}:
            raise GuardError("active slot must be a or b")
    elif cmd.startswith("--set-active="):
        _arity(a, 1)
        if cmd.split("=", 1)[1] not in {"a", "b"}:
            raise GuardError("active slot must be a or b")
    elif cmd in {"flash", "erase", "format", "format:ext4", "format:f2fs"}:
        if len(a) < 2:
            raise GuardError(f"'fastboot {cmd}' without a partition")
        _arity(a, 3 if cmd == "flash" else 2)
        part = a[1]
        if cmd != "flash" and base_name(part) not in _WIPEABLE:
            raise GuardError(f"refusing to {cmd} '{part}': only userdata/metadata/cache may be wiped")
        check_partition(part, fastbootd=fastbootd or logical_ok)
        if cmd == "flash":
            _file_operand(a[2])
            return FileUse(a[2], "flash", part)
    else:
        raise GuardError(f"refusing unknown fastboot command '{cmd}'")


def check_command(tool: str, args: Sequence[str], *, fastbootd: bool = False, logical_ok: bool = False,
                  allow_unlock: bool = False, allow_unlock_placeholder: bool = False) -> FileUse | None:
    """Raise GuardError unless the complete argv matches a supported plan command.

    allow_unlock_placeholder is for plan validation before the executor asks for a
    vendor code. The executor never enables it when checking the resolved command.
    """
    if tool not in {"adb", "fastboot"}:
        raise GuardError(f"unknown tool {tool}")
    a = _arguments(tool, args)
    if tool == "adb":
        return _check_adb(a)
    else:
        return _check_fastboot(a, fastbootd=fastbootd, logical_ok=logical_ok, allow_unlock=allow_unlock,
                              allow_unlock_placeholder=allow_unlock_placeholder)
