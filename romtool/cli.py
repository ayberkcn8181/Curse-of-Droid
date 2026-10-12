"""Command line interface. M1: `tools` and `detect`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .device.detect import detect
from .platform.tools import find_tools, install_platform_tools

_LABELS = [
    ("mode", "Mode"), ("brand", "Brand"), ("model", "Model"), ("codename", "Codename"),
    ("android_version", "Android"), ("security_patch", "Security patch"),
    ("bootloader_unlocked", "Bootloader unlocked"), ("oem_unlock_allowed", "OEM unlocking allowed"),
    ("verified_boot_state", "Verified boot"), ("ab", "A/B slots"), ("current_slot", "Current slot"),
    ("dynamic_partitions", "Dynamic partitions"), ("treble", "Treble"), ("vndk_version", "VNDK"),
    ("abi", "CPU ABI"), ("battery_percent", "Battery %"),
]


def _need_tools():
    tools = find_tools()
    if not tools.complete:
        sys.exit("adb/fastboot not found. Run `romtool tools install` to download Google's platform-tools.")
    return tools


def cmd_tools(args) -> int:
    if args.action == "install":
        tools = install_platform_tools()
        print(f"platform-tools installed: {tools.adb.parent}")
        return 0
    tools = find_tools()
    print(f"adb:      {tools.adb or 'missing'}\nfastboot: {tools.fastboot or 'missing'}\nsource:   {tools.source}")
    return 0 if tools.complete else 1


def cmd_detect(args) -> int:
    tools = _need_tools()
    found = detect(tools.adb, tools.fastboot)
    if args.json:
        print(json.dumps([{"mode": d.mode, "problem": d.problem,
                           "profile": d.profile.to_dict(redact=not args.show_serial) if d.profile else None}
                          for d in found], indent=2))
        return 0 if found else 1
    if not found:
        print("No phone found. Connect it with USB debugging enabled, or in fastboot/recovery mode.")
        return 1
    for d in found:
        print(f"== {d.mode}")
        if d.problem:
            print(f"   ! {d.problem}")
        if not d.profile:
            continue
        p = d.profile.to_dict(redact=not args.show_serial)
        for key, label in _LABELS:
            if p.get(key) not in ("", None, "unknown"):
                print(f"   {label:<22} {p[key]}")
        if len(d.profile.codenames) > 1:
            print(f"   {'Other names':<22} {', '.join(d.profile.codenames[1:])}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="romtool", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tools", help="show or install adb/fastboot (Google platform-tools)")
    t.add_argument("action", nargs="?", choices=["status", "install"], default="status")
    t.set_defaults(func=cmd_tools)
    d = sub.add_parser("detect", help="find connected phones and show what romtool knows about them")
    d.add_argument("--json", action="store_true")
    d.add_argument("--show-serial", action="store_true", help="do not shorten serial numbers")
    d.set_defaults(func=cmd_detect)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
