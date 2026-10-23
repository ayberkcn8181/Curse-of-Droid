"""Turn (device, recovery, ROM) into a plan. First strategy: custom recovery + adb sideload.

This is how LineageOS, crDroid, Evolution X, PixelOS and DerpFest document their installs for most devices.
Device-specific extra steps (copying firmware to the other slot, flashing dtbo/vendor_boot from the ROM's
release) come from the project's instructions and are added per device later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..device.profile import DeviceProfile
from .artifacts import ArtifactError, ArtifactRequirement, require_artifact
from .package import PackageInfo
from .plan import Command, InstallTarget, Plan, Step

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
    elif profile.bootloader_unlocked != "yes":
        problems.append("the bootloader state is unknown; read a confirmed unlocked state before planning")
    if not profile.codenames:
        problems.append("the device codename is unknown")
    if not profile.serial:
        problems.append("an explicit device serial is required")
    if profile.ab not in {"yes", "no"} or profile.ab == "yes" and profile.current_slot not in {"a", "b"}:
        problems.append("a confirmed A/B layout and active slot are required")
    if profile.battery_percent is not None and profile.battery_percent < MIN_BATTERY:
        problems.append(f"battery at {profile.battery_percent}%: charge to at least {MIN_BATTERY}%")
    if req.rom.kind != "ota-zip":
        problems.append(f"{req.rom.path.name} is not an installable ROM package")
    if req.rom.matches(profile.codenames) is False:
        problems.append(f"{req.rom.path.name} is built for {', '.join(req.rom.devices)}, "
                        f"this phone is {', '.join(profile.codenames) or 'unknown'}")
    return problems


def _artifact(profile: DeviceProfile, path: Path, kind: str) -> ArtifactRequirement:
    try:
        artifact = require_artifact(path, kind)
    except ArtifactError as e:
        raise PlanError(str(e)) from None
    device_names = {d.lower() for d in profile.codenames}
    if not device_names.intersection(d.lower() for d in artifact.manifest.devices):
        raise PlanError(f"{path.name}: manifest targets do not match the selected device")
    return artifact


def plan_sideload_install(profile: DeviceProfile, req: InstallRequest) -> Plan:
    if problems := preflight(profile, req):
        raise PlanError("; ".join(problems))
    rom = _artifact(profile, req.rom.path, "rom")
    if req.rom.identity is None or req.rom.identity != rom.identity:
        raise PlanError("ROM package changed since metadata inspection; inspect it again")
    recovery = None
    if req.recovery:
        if req.recovery.suffix.lower() != ".img":
            raise PlanError("recovery must be an unpacked .img with its own manifest")
        recovery = _artifact(profile, req.recovery, "recovery")
    extras = []
    for extra in req.extras:
        if extra.kind != "ota-zip":
            raise PlanError(f"{extra.path.name} is not an installable add-on package")
        if extra.matches(profile.codenames) is False:
            raise PlanError(f"{extra.path.name}: embedded add-on targets do not match the selected device")
        artifact = _artifact(profile, extra.path, "addon")
        if extra.identity is None or extra.identity != artifact.identity:
            raise PlanError("add-on package changed since metadata inspection; inspect it again")
        extras.append(artifact)
    artifacts = (rom,) + ((recovery,) if recovery else ()) + tuple(extras)
    steps: list[Step] = []
    warnings = []
    if req.rom.matches(profile.codenames) is None:
        warnings.append(f"{req.rom.path.name} has no embedded device target; the reviewed manifest supplies it")

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
                              [Command("fastboot", ["flash", req.recovery_partition, str(recovery.path)])]))
            steps.append(Step("Start the recovery",
                              "Use the volume keys to choose 'Recovery mode' and confirm with power.",
                              "reboot", manual="select Recovery mode in the bootloader menu",
                              wait_for="recovery"))
        else:
            steps.append(Step(f"Start {req.recovery_name or 'the recovery'} once",
                              "Boots the recovery image from the computer without writing it to the phone.",
                              "reboot", [Command("fastboot", ["boot", str(recovery.path)])],
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
                      "system-write", [Command("adb", ["sideload", str(rom.path)], timeout=3600)],
                      wait_for="recovery"))
    for extra in extras:
        steps.append(Step(f"Install {extra.path.name}", "Optional add-on, installed right after the ROM "
                          "(before the first boot).", "system-write",
                          [Command("adb", ["sideload", str(extra.path)], timeout=1800)],
                          manual="start ADB sideload again in the recovery", wait_for="recovery"))
    steps.append(Step("Restart into the new system", "The first boot can take several minutes.", "reboot",
                      [Command("adb", ["reboot"])], wait_for="android", wait_timeout=1200))
    return Plan(f"Install {req.rom.path.name} on {profile.brand} {profile.model} ({profile.codename})".strip(),
                steps, warnings, artifacts, InstallTarget.from_profile(profile))


def plan_gsi_install(profile: DeviceProfile, image: Path, wipe_data: bool = True) -> Plan:
    """Flash a GSI system image the way Android's GSI documentation describes it.

    Dynamic partitions: system is a logical partition, written from fastbootd. Legacy devices: the real
    system partition, written from the bootloader. vbmeta is not touched: phones that need verification
    disabled for a GSI need the ROM-specific vbmeta step from their own instructions.
    """
    problems = []
    if profile.bootloader_unlocked == "no":
        problems.append("the bootloader is locked: see `curseofdroid unlock` for this phone")
    elif profile.bootloader_unlocked != "yes":
        problems.append("the bootloader state is unknown; read a confirmed unlocked state before planning")
    if not profile.codenames:
        problems.append("the device codename is unknown")
    if not profile.serial:
        problems.append("an explicit device serial is required")
    if profile.treble != "yes":
        problems.append("confirmed Treble support is required")
    if profile.abi != "arm64-v8a":
        problems.append("a confirmed arm64-v8a ABI is required; 32-bit/binder layouts need further validation")
    if profile.dynamic_partitions not in {"yes", "no"}:
        problems.append("the dynamic partition layout is unknown; it must not be treated as legacy")
    if profile.ab not in {"yes", "no"}:
        problems.append("the A/B slot layout is unknown")
    elif profile.ab == "yes" and profile.current_slot not in {"a", "b"}:
        problems.append("the active A/B slot is unknown")
    elif profile.ab == "no" and profile.system_as_root != "yes":
        problems.append("a confirmed system-as-root layout is required on an A-only device")
    if profile.mode == "fastbootd" and profile.dynamic_partitions == "no":
        problems.append("fastbootd conflicts with the reported legacy partition layout")
    if profile.battery_percent is not None and profile.battery_percent < MIN_BATTERY:
        problems.append(f"battery at {profile.battery_percent}%: charge to at least {MIN_BATTERY}%")
    if image.suffix != ".img":
        problems.append(f"{image.name}: unpack it first (raw .img expected)")
    if problems:
        raise PlanError("; ".join(problems))
    artifact = _artifact(profile, image, "gsi")
    if artifact.manifest.abi != profile.abi or artifact.manifest.layout != "system-as-root":
        raise PlanError("GSI manifest ABI/layout does not match the supported device layout")
    image = artifact.path
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
    return Plan(f"Install {image.name} on {profile.brand} {profile.model} ({profile.codename})", steps, warnings,
                (artifact,), InstallTarget.from_profile(profile))
