"""USB access for adb/fastboot: udev rules on Linux, Google's USB driver on Windows, nothing on macOS.

Installing either needs administrator rights; the tool prints exactly what it will run and asks first.
"""

from __future__ import annotations

import io
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .net import USER_AGENT, verify
from .paths import tools_dir

# USB vendor IDs of phone makers (adb, fastboot, recovery). Download/EDL modes are deliberately not included.
USB_VENDORS = {
    "18d1": "Google", "04e8": "Samsung", "2717": "Xiaomi", "2a70": "OnePlus", "22b8": "Motorola",
    "12d1": "Huawei", "22d9": "OPPO/realme", "0fce": "Sony", "1004": "LG", "0bb4": "HTC", "17ef": "Lenovo",
    "19d2": "ZTE", "0b05": "ASUS", "2e04": "Nokia/HMD", "0e8d": "MediaTek", "05c6": "Qualcomm",
}
UDEV_PATH = Path("/etc/udev/rules.d/51-android.rules")

# Google USB Driver r13, size and SHA-1 as published in Google's SDK repository (addon2-1.xml)
GOOGLE_USB_DRIVER = {"url": "https://dl.google.com/android/repository/usb_driver_r13-windows.zip",
                     "size": 8682039, "sha1": "08a48c39084e9443f6146c239cbd3be6f91e681b"}


def udev_rules() -> str:
    lines = ["# Android devices for adb/fastboot (written by Curse of Droid)"]
    for vid, name in USB_VENDORS.items():
        lines.append(f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{vid}", MODE="0660", TAG+="uaccess"  # {name}')
    return "\n".join(lines) + "\n"


@dataclass
class DriverStatus:
    platform: str
    needed: bool
    installed: bool
    detail: str


def status() -> DriverStatus:
    if sys.platform == "darwin":
        return DriverStatus("macOS", False, True, "macOS needs no USB driver for adb/fastboot.")
    if sys.platform == "win32":
        inf = tools_dir() / "usb_driver" / "android_winusb.inf"
        return DriverStatus("Windows", True, inf.is_file(),
                            "Google USB Driver (Pixel, Android One and most phones in fastboot). Samsung phones "
                            "need Samsung's own USB driver from samsung.com." if not inf.is_file() else
                            f"Google USB Driver downloaded to {inf.parent}.")
    have = UDEV_PATH.is_file() or any(Path("/usr/lib/udev/rules.d").glob("*android*")) \
        or any(Path("/etc/udev/rules.d").glob("*android*"))
    return DriverStatus("Linux", True, have,
                        "udev rules present" if have else f"no Android udev rules; {UDEV_PATH} gives your user "
                                                         "access to phones over USB")


def install_commands() -> list[list[str]]:
    """The privileged commands `install()` runs, so the UI can show them before asking."""
    if sys.platform == "win32":
        inf = tools_dir() / "usb_driver" / "android_winusb.inf"
        return [["pnputil", "/add-driver", str(inf), "/install"]]
    if sys.platform.startswith("linux"):
        return [["pkexec", "sh", "-c", f"cat > {UDEV_PATH} && udevadm control --reload-rules && udevadm trigger"]]
    return []


def download_google_usb_driver() -> Path:
    d = GOOGLE_USB_DRIVER
    req = urllib.request.Request(d["url"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    tmp = tools_dir() / "usb_driver_r13-windows.zip"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(data)
    verify(tmp, size=d["size"], hashes={"sha1": d["sha1"]})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(tools_dir())  # contains usb_driver/
    tmp.unlink()
    return tools_dir() / "usb_driver"


def install() -> None:
    """Needs admin rights: UAC on Windows (pnputil from an elevated prompt), polkit/pkexec on Linux."""
    if sys.platform == "win32":
        download_google_usb_driver()
        for cmd in install_commands():
            subprocess.run(cmd, check=True)
    elif sys.platform.startswith("linux"):
        for cmd in install_commands():
            subprocess.run(cmd, input=udev_rules(), text=True, check=True)
