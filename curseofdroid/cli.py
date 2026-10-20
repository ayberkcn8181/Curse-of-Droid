"""Command line interface: tools, drivers, detect, find, download, unlock, install, gsi."""

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
from .catalog.deviceinfo import device_info
from .catalog.gsi import gsi_fit, trebledroid_builds, unpack_xz
from .flash.planner import InstallRequest, PlanError, plan_gsi_install, plan_sideload_install
from .platform import drivers
from .vendors import vendor_for
from .platform.net import VerificationError, download
from .platform.paths import downloads_dir
from .platform.tools import find_tools, install_platform_tools
from .transport.base import TransportError

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


_connected = None  # profile of the phone _codenames() used, for brand/model hints


def _codenames(args) -> list[str]:
    global _connected
    if args.codename:
        return args.codename
    tools = _need_tools()
    found = [d for d in detect(tools.adb, tools.fastboot) if d.profile and d.profile.codenames]
    if not found:
        sys.exit("No phone with a known codename connected; give the codename, e.g. `curseofdroid find lavender`.")
    names = found[0].profile.codenames
    _connected = found[0].profile
    print(f"Device: {found[0].profile.brand} {found[0].profile.model} ({', '.join(names)})\n")
    return names


def _provider_names(args) -> list:
    if not args.project:
        return ALL_PROVIDERS
    wanted = {p.lower().replace(" ", "") for p in args.project}
    return [p for p in ALL_PROVIDERS if p.name.lower().replace(" ", "") in wanted]


def print_device_info(info) -> None:
    title = " ".join(x for x in (info.vendor, info.name) if x) or info.codename
    print(f"== {title} (codename {info.codename})")
    if info.phones:
        print("   Sold as:")
        for m in info.phones:
            models = f"  [{', '.join(m.models[:8])}{' …' if len(m.models) > 8 else ''}]" if m.models else ""
            name = m.name if m.name.lower().startswith(m.brand.lower()) else f"{m.brand} {m.name}"
            print(f"     {name}{models}")
    elif not info.specs:
        print("   No public catalog entry for this codename.")
    for k, v in info.specs.items():
        print(f"   {k + ':':<24}{v}")
    print()


def cmd_find(args) -> int:
    names = _codenames(args)
    info = None
    if not args.no_info:
        hint = _connected.brand if _connected else ""
        models = [_connected.model] if _connected and _connected.model else []
        info = device_info(names[0], hint, models)
        if not args.json:
            print_device_info(info)
    results, errors = find_builds(names, _provider_names(args))
    if args.json:
        out = {k: [{"version": b.version, "android": b.android, "date": str(b.date or ""),
                               "variant": b.variant, "file": b.main.filename, "url": b.main.url,
                               "size": b.main.size, "hashes": b.main.hashes, "info": b.info_url}
                    for b in v] for k, v in results.items()}
        if info:
            from dataclasses import asdict
            out = {"device": asdict(info), "builds": out}
        print(json.dumps(out, indent=2))
        return 0 if results else 1
    for project, builds in results.items():
        b = builds[0]
        kind = "recovery" if b.kind == "recovery" else "ROM"
        stale = "  (no build for 6+ months)" if is_stale(b) else ""
        android = f" · Android {b.android}" if b.android else ""
        date = f" · {b.date}" if b.date else ""
        size = f" · {b.main.size / 2**30:.2f} GiB" if b.main.size else ""
        variant = f" · {b.variant}" if b.variant and b.kind != "recovery" and "(" in b.variant else ""
        print(f"{project:<19} {kind:<8} {b.version}{android}{date}{size}{variant}{stale}")
        pad = " " * 28
        print(f"{pad}{b.main.filename}")
        if b.notes:
            print(f"{pad}note: {b.notes}")
        if b.info_url:
            print(f"{pad}{b.info_url}")
        if len(builds) > 1:
            print(f"{pad}(+{len(builds) - 1} older/other variants: --json)")
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
    if not b.main.direct:
        print(f"{p.name} publishes no direct download for this device. Get it from: {b.main.url}")
        return 1
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

    def ask(self, step):
        return input(f"   {step.ask}: ")

    def manual(self, step):
        answer = input(f"   On the phone: {step.manual}\n   Press Enter when done (q to stop): ").strip().lower()
        return answer != "q"


def cmd_install(args) -> int:
    tools = _need_tools()
    dev = _one_device(tools)
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


def _one_device(tools):
    found = [d for d in detect(tools.adb, tools.fastboot) if d.profile]
    if len(found) != 1:
        sys.exit("Connect exactly one phone (found %d)." % len(found))
    return found[0]


def cmd_unlock(args) -> int:
    tools = _need_tools()
    dev = _one_device(tools)
    p = dev.profile
    vendor = vendor_for(p)
    info = vendor.info(p)
    print(f"{p.market_name or (p.brand + ' ' + p.model)} — bootloader unlocked: {p.bootloader_unlocked}\n")
    if p.bootloader_unlocked == "yes":
        print("The bootloader is already unlocked; nothing to do.")
        return 0
    print(info.summary() + "\n")
    for i, s in enumerate(info.steps, 1):
        print(f"  {i}. {s}")
    for n in info.notes:
        print(f"  note: {n}")
    for link in info.links:
        print(f"  {link}")
    plan = vendor.unlock_plan(p) if info.automated or info.official else None
    if plan is None:
        if not info.official:
            return 1
        print("\nThis vendor's procedure runs in its own tool/website; follow the steps above.")
        return 0
    print("\n" + plan.render())
    if args.dry_run:
        print("\n(dry run: nothing was done)")
        return 0
    if input("\nStart? Unlocking ERASES the phone. Type 'yes': ").strip().lower() != "yes":
        return 1
    try:
        Executor(tools.adb, tools.fastboot, dev.serial, ConsoleUI()).run(plan)
    except StepFailed as e:
        print(f"\nStopped: {e}")
        return 1
    print("\nDone. The phone resets itself; set it up again (or continue with `install`).")
    return 0


def cmd_gsi(args) -> int:
    tools = _need_tools()
    dev = _one_device(tools)
    p = dev.profile
    if args.install:
        image = Path(args.install)
        if image.name.endswith(".xz"):
            print(f"Unpacking {image.name} …")
            image = unpack_xz(image)
        try:
            plan = plan_gsi_install(p, image, wipe_data=not args.keep_data)
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
            return 1
        print("\nDone.")
        return 0
    fit = gsi_fit(p)
    print(f"{p.market_name or p.brand + ' ' + p.model}: GSI {'possible' if fit.ok else 'not possible'}"
          + (f" ({fit.arch})" if fit.arch else ""))
    for r in fit.reasons:
        print(f"  - {r}")
    if not fit.ok:
        return 1
    builds = trebledroid_builds(p)
    for b in builds:
        print(f"  {b.project} {b.version} · {b.variant} · {b.main.size / 2**30:.2f} GiB · {b.main.filename}")
    if args.download and builds:
        b = builds[1] if args.old and len(builds) > 1 else builds[0]
        dest = downloads_dir() / "gsi" / b.main.filename
        print(f"Downloading {b.main.filename} (TrebleDroid publishes no checksum; size is checked) …")
        download(b.main.url, dest, size=b.main.size,
                 progress=lambda d, t: print(f"\r  {d * 100 // t if t else 0:3d}%", end="", flush=True))
        print(f"\nUnpacking … {unpack_xz(dest)}")
    return 0


def cmd_drivers(args) -> int:
    st = drivers.status()
    print(f"{st.platform}: {st.detail}")
    if args.action == "status" or not st.needed:
        return 0
    if sys.platform.startswith("linux"):
        print("\nRules to install:\n" + drivers.udev_rules())
    for cmd in drivers.install_commands():
        print("$ " + " ".join(cmd))
    if input("\nThis needs administrator rights. Type 'yes' to continue: ").strip().lower() != "yes":
        return 1
    drivers.install()
    print("Installed. Reconnect the phone.")
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
    f.add_argument("--no-info", action="store_true", help="skip the device/market-name lookup")
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
    u = sub.add_parser("unlock", help="check the bootloader and unlock it with the vendor's official method")
    u.add_argument("--dry-run", action="store_true")
    u.set_defaults(func=cmd_unlock)
    g = sub.add_parser("gsi", help="Generic System Images for Treble phones without an official ROM")
    g.add_argument("--download", action="store_true", help="download and unpack the newest matching GSI")
    g.add_argument("--old", action="store_true", help="the alternative '-old' build instead")
    g.add_argument("--install", metavar="IMAGE", help="flash a GSI image (.img or .img.xz)")
    g.add_argument("--keep-data", action="store_true")
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(func=cmd_gsi)
    dr = sub.add_parser("drivers", help="USB access: udev rules (Linux) or Google's USB driver (Windows)")
    dr.add_argument("action", nargs="?", choices=["status", "install"], default="status")
    dr.set_defaults(func=cmd_drivers)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except TransportError as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
