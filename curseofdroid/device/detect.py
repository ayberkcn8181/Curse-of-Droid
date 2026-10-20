"""Find connected phones in any mode and build their profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..transport.adb import Adb
from ..transport.base import Runner, TransportError, subprocess_runner
from ..transport.fastboot import Fastboot
from .profile import DeviceProfile, Mode, from_fastboot, from_props

_ADB_MODES: dict[str, Mode] = {"device": "android", "recovery": "recovery", "sideload": "sideload"}


@dataclass
class Detected:
    serial: str
    mode: Mode
    profile: DeviceProfile | None
    problem: str = ""  # e.g. "unauthorized": user must accept the RSA prompt on the phone


def detect(adb_exe, fastboot_exe, runner: Runner = subprocess_runner) -> list[Detected]:
    found: list[Detected] = []
    adb = Adb(adb_exe, runner)
    for dev in adb.devices():
        if dev.state == "unauthorized":
            found.append(Detected(dev.serial, "android", None,
                                  "unauthorized: allow USB debugging on the phone's screen"))
            continue
        if dev.state == "offline":
            found.append(Detected(dev.serial, "unknown", None, "offline: reconnect the cable"))
            continue
        mode = _ADB_MODES.get(dev.state, "unknown")
        if mode == "sideload":  # no shell in sideload mode
            found.append(Detected(dev.serial, mode, DeviceProfile(mode=mode, serial=dev.serial)))
            continue
        one = Adb(adb_exe, runner, serial=dev.serial)
        profile = from_props(one.getprop(), mode, dev.serial)
        profile.battery_percent = _battery_from_shell(one)
        found.append(Detected(dev.serial, mode, profile))
    fb = Fastboot(fastboot_exe, runner)
    for serial, mode in fb.devices():
        one = Fastboot(fastboot_exe, runner, serial=serial)
        m: Mode = "fastbootd" if mode == "fastbootd" else "fastboot"
        found.append(Detected(serial, m, from_fastboot(one.getvar_all(), m, serial)))
    return found


def _battery_from_shell(adb: Adb) -> int | None:
    try:
        out = adb.shell("cat /sys/class/power_supply/battery/capacity 2>/dev/null || dumpsys battery 2>/dev/null")
    except TransportError:
        return None  # Battery information is optional, especially in recovery.
    out = out.strip()
    if out.isdigit():
        return int(out)
    m = re.search(r"level:\s*(\d+)", out)
    return int(m.group(1)) if m else None
