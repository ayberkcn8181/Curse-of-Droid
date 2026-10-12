"""Bootloader unlocking, per vendor, through the vendor's official procedure only.

Wording matters: "no official method" is not "can't be unlocked". If a user unlocks a phone some other way, the
tool reads the real state from the device and carries on — it never refuses an install because of what this table
says. What the tool itself never does is run an unofficial unlock (exploits, EDL/BROM, paid unlock services).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..device.profile import DeviceProfile
from ..flash.plan import Command, Plan, Step


@dataclass
class UnlockInfo:
    vendor: str
    official: bool  # an official unlock procedure exists for this vendor (model exceptions in notes)
    method: str  # short name of the procedure
    steps: list[str]  # what the user has to do, in order
    links: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    automated: bool = False  # the tool can run the fastboot part

    def summary(self) -> str:
        if self.official:
            return f"{self.vendor}: official unlock — {self.method}"
        return (f"{self.vendor}: no official unlock method is known, so a custom ROM/recovery can't be installed "
                f"the official way. If the bootloader gets unlocked by other means, this tool detects it and "
                f"can continue.")


class Vendor:
    name = "Generic"
    brands: tuple[str, ...] = ()

    def info(self, profile: DeviceProfile) -> UnlockInfo:
        raise NotImplementedError

    def unlock_plan(self, profile: DeviceProfile) -> Plan | None:
        """Plan for the automatable part, or None when the procedure is manual/vendor-tool based."""
        return None


# ---- shared fastboot procedure ------------------------------------------------------------------------------

def _enable_oem_unlocking_step(profile: DeviceProfile) -> list[Step]:
    if profile.oem_unlock_allowed == "yes":
        return []
    return [Step("Allow OEM unlocking",
                 "Android only lets the bootloader be unlocked after this switch is turned on.",
                 manual="Settings → About phone → tap 'Build number' 7 times; then Settings → System → "
                        "Developer options → turn on 'OEM unlocking' (needs internet on some phones)")]


def fastboot_unlock_plan(profile: DeviceProfile, vendor: str, command: list[str]) -> Plan:
    steps = _enable_oem_unlocking_step(profile)
    if profile.mode in ("android", "recovery", "unknown"):
        steps.append(Step("Reboot to fastboot", "The phone restarts into its bootloader; nothing is changed.",
                          "reboot", [Command("adb", ["reboot", "bootloader"])], wait_for="fastboot"))
    steps.append(Step("Unlock the bootloader",
                      "Unlocking ERASES EVERYTHING on the phone (apps, accounts, photos) and may void the "
                      "warranty. The phone asks for confirmation on its screen.",
                      "data-loss", [Command("fastboot", command)], unlock=True,
                      manual="when the phone asks, use the volume keys to select 'Unlock the bootloader' and "
                             "confirm with the power key"))
    steps.append(Step("Check the result", "Reads the lock state back from the bootloader.",
                      commands=[Command("fastboot", ["getvar", "unlocked"])]))
    return Plan(f"Unlock the bootloader of {profile.brand} {profile.model} ({vendor})", steps,
                ["Back up everything first: unlocking wipes the phone."])


# ---- registry ----------------------------------------------------------------------------------------------

def vendor_for(profile: DeviceProfile) -> Vendor:
    from . import vendors
    key = f"{profile.brand} {profile.manufacturer}".lower()
    for cls in vendors.ALL:
        if any(b in key for b in cls.brands):
            return cls()
    return vendors.Generic()
