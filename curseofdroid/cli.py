"""Command line interface: `tools`, `detect`, `find`, `download`, `install`."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .catalog.providers import ALL_PROVIDERS, TWRP, find_builds, is_stale
from pathlib import Path

from .device.detect import detect
from .flash.executor import Executor, StepFailed
from .flash.package import inspect as inspect_package
from .flash.planner import InstallRequest, PlanError, plan_sideload_install
from .platform.net import VerificationError, download
from .platform.paths import downloads_dir
from .platform.tools import find_tools, install_platform_tools

_LABELS = [
    ("mode", "Mode"), ("brand", "Brand"), ("market_name", "Name"), ("model", "Model"), ("codename", "Codename"),
    ("soc", "SoC"),
    ("android_version", "Android"), ("security_patch", "Security patch"),
    ("bootloader_unlocked", "Bootloader unlocked"), ("oem_unlock_allowed", "OEM unlocking allowed"),
    ("verified_boot_state", "Verified boot"), ("ab", "A/B slots"), ("current_slot", "Current slot"),
    ("dynamic_partitions", "Dynamic partitions"), ("virtual_ab", "Virtual A/B"), ("treble", "Treble"), ("vndk_version", "VNDK"),
    ("abi", "CPU ABI"), ("battery_percent", "Battery %"),
]


def _need_tools():
    tools = find_tools()
    if not tools.complete:
        sys.exit("adb/fastboot not found. Run `curseofdroid tools install` to download Google's platform-tools.")
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
        if d.profile.boot_partitions:
            print(f"   {'Boot partitions':<22} boot, {', '.join(d.profile.boot_partitions)}")
        if len(d.profile.codenames) > 1:
            print(f"   {'Other names':<22} {', '.join(d.profile.codenames[1:])}")
    return 0


def _codenames(args) -> list[str]:
    if args.codename:
        return args.codename
    tools = _need_tools()
    found = [d for d in detect(tools.adb, tools.fastboot) if d.profile and d.profile.codenames]
    if not found:
        sys.exit("No phone with a known codename connected; give the codename, e.g. `curseofdroid find lavender`.")
    names = found[0].profile.codenames
    print(f"Device: {found[0].profile.brand} {found[0].profile.model} ({', '.join(names)})\n")
    return names


def _provider_names(args) -> list:
    if not args.project:
        return ALL_PROVIDERS
    wanted = {p.lower().replace(" ", "") for p in args.project}
    return [p for p in ALL_PROVIDERS if p.name.lower().replace(" ", "") in wanted]


def cmd_find(args) -> int:
    results, errors = find_builds(_codenames(args), _provider_names(args))
    if args.json:
        print(json.dumps({k: [{"version": b.version, "android": b.android, "date": str(b.date or ""),
                               "variant": b.variant, "file": b.main.filename, "url": b.main.url,
                               "size": b.main.size, "hashes": b.main.hashes, "info": b.info_url}
                              for b in v] for k, v in results.items()}, indent=2))
        return 0 if results else 1
    for project, builds in results.items():
        b = builds[0]
        kind = "recovery" if b.kind == "recovery" else "ROM"
        stale = "  (no build for 6+ months)" if is_stale(b) else ""
        android = f" · Android {b.android}" if b.android else ""
        date = f" · {b.date}" if b.date else ""
        size = f" · {b.main.size / 2**30:.2f} GiB" if b.main.size else ""
        print(f"{project:<12} {kind:<8} {b.version}{android}{date}{size}{stale}")
        print(f"{'':<21} {b.main.filename}")
        if b.info_url:
            print(f"{'':<21} {b.info_url}")
        if len(builds) > 1:
            print(f"{'':<21} (+{len(builds) - 1} older/other variants: --json)")
    for e in errors:
        print(f"! {e}", file=sys.stderr)
    if not results:
        print("No official builds found. GSIs or a local build may still be possible (later milestones).")
    return 0 if results else 1


def cmd_download(args) -> int:
    providers = _provider_names(args)
    if len(providers) != 1:
        sys.exit("Choose exactly one project with --project (e.g. --project LineageOS).")
    p = providers[0]()
    builds = []
    for c in _codenames(args):
        if builds := p.builds(c):
            break
    if not builds:
        sys.exit(f"{p.name} has no build for this device.")
    b = builds[0]
    if isinstance(p, TWRP):
        p.fill_hash(b)
    dest = downloads_dir() / b.codename / b.main.filename
    if not b.main.hashes:
        print("! The project publishes no checksum for this file; only the size can be checked.")
    print(f"Downloading {b.main.filename} -> {dest}")

    def progress(done, total):
        pct = f"{done * 100 // total:3d}%" if total else f"{done // 2**20} MiB"
        print(f"\r  {pct}", end="", flush=True)

    try:
        download(b.main.url, dest, size=b.main.size, hashes=b.main.hashes, headers=b.main.headers,
                 progress=progress)
    except VerificationError as e:
        print(f"\nVerification failed: {e}. The partial file was kept as .part; try again.")
        return 1
    print(f"\nVerified ({', '.join(b.main.hashes) or 'size'}): {dest}")
    return 0


class ConsoleUI:
    def info(self, text):
        print(text)

    def confirm(self, step):
        print(f"\n   {step.explain}")
        answer = input(f"   This step is [{step.risk}]. Type 'yes' to continue: ").strip().lower()
        return answer == "yes"

    def manual(self, step):
        answer = input(f"   On the phone: {step.manual}\n   Press Enter when done (q to stop): ").strip().lower()
        return answer != "q"


def cmd_install(args) -> int:
    tools = _need_tools()
    found = [d for d in detect(tools.adb, tools.fastboot) if d.profile]
    if len(found) != 1:
        sys.exit("Connect exactly one phone (found %d)." % len(found))
    dev = found[0]
    rom = inspect_package(Path(args.rom))
    req = InstallRequest(rom, recovery=Path(args.recovery) if args.recovery else None,
                         recovery_name=args.recovery_name or "", flash_recovery=args.flash_recovery,
                         recovery_partition=args.recovery_partition, wipe_data=not args.keep_data,
                         extras=tuple(inspect_package(Path(x)) for x in args.extra or []))
    try:
        plan = plan_sideload_install(dev.profile, req)
    except PlanError as e:
        print(f"Can't install: {e}")
        return 1
    print(plan.render())
    if args.dry_run:
        print("\n(dry run: nothing was done)")
        return 0
    if input("\nStart? Type 'yes': ").strip().lower() != "yes":
        return 1
    try:
        Executor(tools.adb, tools.fastboot, dev.serial, ConsoleUI()).run(plan)
    except StepFailed as e:
        print(f"\nStopped: {e}")
        print("Nothing after this step was done. The phone can be put into fastboot (power + volume down) "
              "or recovery mode to try again.")
        return 1
    print("\nDone.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="curseofdroid", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tools", help="show or install adb/fastboot (Google platform-tools)")
    t.add_argument("action", nargs="?", choices=["status", "install"], default="status")
    t.set_defaults(func=cmd_tools)
    d = sub.add_parser("detect", help="find connected phones and show what curseofdroid knows about them")
    d.add_argument("--json", action="store_true")
    d.add_argument("--show-serial", action="store_true", help="do not shorten serial numbers")
    d.set_defaults(func=cmd_detect)
    f = sub.add_parser("find", help="list official ROM and recovery builds for the device")
    f.add_argument("codename", nargs="*", help="device codename(s); default: the connected phone")
    f.add_argument("--project", action="append", help="limit to a project (repeatable)")
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_find)
    dl = sub.add_parser("download", help="download and verify the newest build from one project")
    dl.add_argument("codename", nargs="*")
    dl.add_argument("--project", action="append", required=True)
    dl.set_defaults(func=cmd_download)
    i = sub.add_parser("install", help="install a ROM through a custom recovery (adb sideload)")
    i.add_argument("--rom", required=True, help="ROM zip (from `download` or your own)")
    i.add_argument("--recovery", help="recovery image to boot (or flash with --flash-recovery)")
    i.add_argument("--recovery-name", help="e.g. TWRP, OrangeFox, LineageOS Recovery")
    i.add_argument("--flash-recovery", action="store_true", help="write the recovery instead of booting it once")
    i.add_argument("--recovery-partition", default="recovery", choices=["recovery", "boot", "vendor_boot"])
    i.add_argument("--keep-data", action="store_true", help="don't format data (only for updates of the same ROM)")
    i.add_argument("--extra", action="append", help="zip to sideload after the ROM (GApps, ...)")
    i.add_argument("--dry-run", action="store_true", help="only print the plan")
    i.set_defaults(func=cmd_install)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
