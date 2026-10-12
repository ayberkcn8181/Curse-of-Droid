"""Turn (device, recovery, ROM) into a plan. First strategy: custom recovery + adb sideload.

This is how LineageOS, crDroid, Evolution X, PixelOS and DerpFest document their installs for most devices.
Device-specific extra steps (copying firmware to the other slot, flashing dtbo/vendor_boot from the ROM's
release) come from the project's instructions and are added per device later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..device.profile import DeviceProfile
from .package import PackageInfo
from .plan import Command, Plan, Step

MIN_BATTERY = 50


class PlanError(Exception):
    pass


@dataclass
class InstallRequest:
    rom: PackageInfo
    recovery: Path | None = None  # recovery image; None = a working custom recovery is already installed
    recovery_name: str = ""  # "TWRP", "OrangeFox", "LineageOS Recovery" ...
    flash_recovery: bool = False  # write it (otherwise boot it once with `fastboot boot`)
    recovery_partition: str = "recovery"  # recovery | boot | vendor_boot (from the ROM project's instructions)
    wipe_data: bool = True  # required when coming from another ROM
    extras: tuple[PackageInfo, ...] = ()  # GApps, Magisk ... sideloaded after the ROM


def preflight(profile: DeviceProfile, req: InstallRequest) -> list[str]:
    """Problems that block the install (empty list = OK)."""
    problems = []
    if profile.bootloader_unlocked == "no":
        problems.append("the bootloader is locked: see `curseofdroid unlock` for this phone")
    if profile.battery_percent is not None and profile.battery_percent < MIN_BATTERY:
        problems.append(f"battery at {profile.battery_percent}%: charge to at least {MIN_BATTERY}%")
    if req.rom.kind == "unknown":
        problems.append(f"{req.rom.path.name} is not an installable ROM package")
    if req.rom.matches(profile.codenames) is False:
        problems.append(f"{req.rom.path.name} is built for {', '.join(req.rom.devices)}, "
                        f"this phone is {', '.join(profile.codenames) or 'unknown'}")
    return problems


def plan_sideload_install(profile: DeviceProfile, req: InstallRequest) -> Plan:
    if problems := preflight(profile, req):
        raise PlanError("; ".join(problems))
    steps: list[Step] = []
    warnings = []
    if profile.bootloader_unlocked == "unknown":
        warnings.append("couldn't read the bootloader state; fastboot will refuse to flash if it is locked")
    if req.rom.matches(profile.codenames) is None:
        warnings.append(f"{req.rom.path.name} doesn't name its target device; make sure it is for this phone")

    if profile.mode in ("android", "unknown"):
        target = "bootloader" if req.recovery else "recovery"
        steps.append(Step(f"Reboot to {'fastboot' if req.recovery else 'recovery'}",
                          "The phone restarts; nothing is changed.", "reboot",
                          [Command("adb", ["reboot", target])],
                          wait_for="fastboot" if req.recovery else "recovery"))
    if req.recovery:
        if req.flash_recovery:
            steps.append(Step(f"Install {req.recovery_name or 'the recovery'}",
                              f"Writes {req.recovery.name} to the {req.recovery_partition} partition.",
                              "system-write",
                              [Command("fastboot", ["flash", req.recovery_partition, str(req.recovery)])]))
            steps.append(Step("Start the recovery",
                              "Use the volume keys to choose 'Recovery mode' and confirm with power.",
                              "reboot", manual="select Recovery mode in the bootloader menu",
                              wait_for="recovery"))
        else:
            steps.append(Step(f"Start {req.recovery_name or 'the recovery'} once",
                              "Boots the recovery image from the computer without writing it to the phone.",
                              "reboot", [Command("fastboot", ["boot", str(req.recovery)])],
                              wait_for="recovery"))
    if req.wipe_data:
        steps.append(Step("Erase user data",
                          "Formats the data partition: apps, accounts, settings and internal storage "
                          "(photos, downloads) are deleted. Needed when switching ROMs.",
                          "data-loss",
                          manual="in the recovery choose Wipe/Factory reset → Format data, then come back here"))
    steps.append(Step("Start sideload mode", "The recovery waits for the ROM package from the computer.",
                      manual="choose Apply update → Apply from ADB (TWRP: Advanced → ADB Sideload)",
                      wait_for="sideload"))
    steps.append(Step(f"Install {req.rom.path.name}", "Sends the ROM to the recovery, which installs it.",
                      "system-write", [Command("adb", ["sideload", str(req.rom.path)], timeout=3600)],
                      wait_for="recovery"))
    for extra in req.extras:
        steps.append(Step(f"Install {extra.path.name}", "Optional add-on, installed right after the ROM "
                          "(before the first boot).", "system-write",
                          [Command("adb", ["sideload", str(extra.path)], timeout=1800)],
                          manual="start ADB sideload again in the recovery", wait_for="recovery"))
    steps.append(Step("Restart into the new system", "The first boot can take several minutes.", "reboot",
                      [Command("adb", ["reboot"])], wait_for="android", wait_timeout=1200))
    return Plan(f"Install {req.rom.path.name} on {profile.brand} {profile.model} ({profile.codename})".strip(),
                steps, warnings)


def plan_gsi_install(profile: DeviceProfile, image: Path, wipe_data: bool = True) -> Plan:
    """Flash a GSI system image the way Android's GSI documentation describes it.

    Dynamic partitions: system is a logical partition, written from fastbootd. Legacy devices: the real
    system partition, written from the bootloader. vbmeta is not touched: phones that need verification
    disabled for a GSI need the ROM-specific vbmeta step from their own instructions.
    """
    problems = []
    if profile.bootloader_unlocked == "no":
        problems.append("the bootloader is locked: see `curseofdroid unlock` for this phone")
    if profile.battery_percent is not None and profile.battery_percent < MIN_BATTERY:
        problems.append(f"battery at {profile.battery_percent}%: charge to at least {MIN_BATTERY}%")
    if image.suffix != ".img":
        problems.append(f"{image.name}: unpack it first (raw .img expected)")
    if problems:
        raise PlanError("; ".join(problems))
    dynamic = profile.dynamic_partitions == "yes"
    steps: list[Step] = []
    if profile.mode in ("android", "recovery", "unknown"):
        steps.append(Step("Reboot to fastboot", "Nothing is changed.", "reboot",
                          [Command("adb", ["reboot", "bootloader"])], wait_for="fastboot"))
    if dynamic:
        steps.append(Step("Switch to fastbootd", "System lives inside the 'super' partition on this phone; "
                          "it can only be written from the userspace fastboot (fastbootd).", "reboot",
                          [Command("fastboot", ["reboot", "fastboot"])], wait_for="fastbootd"))
    if wipe_data:
        steps.append(Step("Erase user data", "A new system needs clean data: apps, accounts and internal "
                          "storage are deleted.", "data-loss", [Command("fastboot", ["-w"])], fastbootd=dynamic))
    steps.append(Step(f"Write {image.name} to system", "Replaces the phone's system with the GSI; vendor, boot "
                      "and firmware stay as they are.", "system-write",
                      [Command("fastboot", ["flash", "system", str(image)], timeout=1800, logical_ok=not dynamic)],
                      fastbootd=dynamic))
    steps.append(Step("Restart", "The first boot can take several minutes.", "reboot",
                      [Command("fastboot", ["reboot"])], wait_for="android", wait_timeout=1200))
    warnings = ["A GSI runs on this phone's own vendor software; some hardware may not work.",
                "If the phone doesn't boot (returns to the bootloader), it may need verified boot disabled with "
                "its own vbmeta step — follow the device's GSI instructions; this tool doesn't do that by default."]
    return Plan(f"Install {image.name} on {profile.brand} {profile.model} ({profile.codename})", steps, warnings)
