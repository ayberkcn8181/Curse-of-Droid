# Curse of Droid

Install custom ROMs and custom recoveries on Android phones — on Windows, Linux and macOS.
Curse of Droid detects the phone, sets up adb/fastboot and drivers, checks the bootloader and unlocks it through the
vendor's official procedure, finds a matching ROM (LineageOS, crDroid, Evolution X, PixelOS, DerpFest, GSIs) and
recovery (TWRP, OrangeFox, LineageOS Recovery), verifies the downloads and flashes them — asking before every
destructive step. If no build exists it can, with your permission, build one locally.

**Status: early development — milestones 1–4** (tool setup, USB drivers/udev, device detection, build catalog,
verified downloads, official bootloader unlock flows, recovery + sideload install with a command guard). Tested on one real device so far; use `--dry-run` first.
See [DESIGN.md](DESIGN.md) for the plan and the deliberate limits (official unlock methods only, firmware
partitions are never written).

## Try it

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/curseofdroid tools install   # downloads Google's platform-tools into its data directory
.venv/bin/curseofdroid detect          # Android (USB debugging), recovery, fastboot or fastbootd
.venv/bin/curseofdroid detect --json
.venv/bin/curseofdroid find            # official builds for the connected phone (or: curseofdroid find <codename>)
.venv/bin/curseofdroid download lavender --project TWRP   # newest build, size + checksum verified
```

Bootloader:

```bash
curseofdroid unlock --dry-run   # the vendor's official procedure for the connected phone, and the plan
curseofdroid drivers install    # Linux: udev rules (asks for admin); Windows: Google USB Driver (verified)
```

Automated: Google Pixel, OnePlus, Nothing (`fastboot flashing unlock`), Motorola (unlock data → code from
Motorola → `fastboot oem unlock`). Guided: Xiaomi (Mi Unlock), Samsung (Download mode), Sony (code). For brands
without an official method (e.g. current OPPO/realme, Huawei/Honor) the tool says so — it does not claim the
phone can't be unlocked, and if the bootloader is unlocked by other means it detects that and continues.

Install through a custom recovery:

```bash
curseofdroid install --rom ROM.zip --recovery twrp.img --recovery-name TWRP --dry-run   # print the plan only
curseofdroid install --rom ROM.zip --recovery twrp.img --recovery-name TWRP --extra gapps.zip
```

The recovery is booted once from the computer (`fastboot boot`) unless `--flash-recovery` is given. Every step that
erases data or writes the system asks you to type `yes`. Before anything runs, every command of the plan passes a
guard: only known fastboot commands, writes only to OS/recovery partitions, wipes only of userdata/metadata/cache,
never firmware partitions, never relocking. A ROM zip that names a different device is refused.

Sources: LineageOS (download API), crDroid, Evolution X, DerpFest (their OTA JSON repos), PixelOS
(official_devices API), TWRP (dl.twrp.me + published .sha256), OrangeFox (API v3).

Detection is read-only. Serial numbers are shortened in the output unless `--show-serial` is given.

## License

GPL-3.0-or-later.
