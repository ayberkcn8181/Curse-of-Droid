# Curse of Droid

Install custom ROMs and custom recoveries on Android phones — on Windows, Linux and macOS.
Curse of Droid detects the phone, sets up adb/fastboot and drivers, checks the bootloader and unlocks it through the
vendor's official procedure, finds a matching ROM (LineageOS, crDroid, Evolution X, PixelOS, DerpFest, GSIs) and
recovery (TWRP, OrangeFox, LineageOS Recovery), verifies the downloads and flashes them — asking before every
destructive step. Local ROM building remains planned.

**Status: early development — milestones 1–5** (tool setup, USB drivers/udev, device detection, build catalog,
verified downloads from 19 ROM projects, official bootloader unlock flows, recovery + sideload install with a command guard, desktop app). Tested on one real device so far; use `--dry-run` first.
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

`find` first shows what the codename is: the phones sold under it (marketing names and model numbers from Google
Play's device catalog — TVs, boxes and tablets that share a codename are left out, and only the phone's brand
family is shown) and specs from the LineageOS wiki (SoC, RAM, screen, battery, how to reach recovery/fastboot).

ROM sources (19): LineageOS, crDroid, Evolution X (all Android branches, vanilla builds too), PixelOS, DerpFest,
Paranoid Android, RisingOS, Project Infinity-X, AxionOS, VoltageOS, YAAP, /e/OS (official, then community),
iodéOS, GrapheneOS and CalyxOS (both listed with their own installers — not installed through a recovery),
and the ended projects PixelExperience, ArrowOS, Havoc-OS (last builds, from their surviving mirrors, marked as
ended) and Project Elixir (its device list only links to download pages). Recoveries: TWRP (published .sha256),
OrangeFox. GSIs: TrebleDroid.

Detection is read-only. Serial numbers are shortened in the output unless `--show-serial` is given.

## GSIs (Treble phones without an official ROM)

```bash
curseofdroid gsi                    # does a GSI fit this phone? (Treble, CPU, system-as-root, vendor age)
curseofdroid gsi --download         # newest TrebleDroid build for the phone's CPU, unpacked to .img
curseofdroid gsi --install system-td-arm64-vanilla.img --dry-run
```

On phones with dynamic partitions the system image is written from fastbootd. vbmeta is not touched by default;
phones that need verified boot disabled for a GSI need their own device-specific step. TrebleDroid publishes no
checksums, so only the download size can be verified.

## Desktop app

```bash
.venv/bin/pip install -e ".[gui]"
.venv/bin/curseofdroid-gui
```

The Qt Quick workspace includes a live Dashboard, explicit device selection, device details, session activity
and Appearance settings. The QML ROM Library and Recovery Manager use the existing provider registry
with streaming searches, filters, metadata details, cancellation and HTTPS source links. Catalog matches
do not certify installation compatibility. Direct files enter the persistent QML Downloads queue, with
pause/resume, retry, publisher checksum checks, file rechecking and folder access. Missing/weak checks
are labeled explicitly; restored history requires checks again. See [download details](docs/QML_DOWNLOADS.md).
Light, dark and system themes apply immediately; theme, accent, workspace scale and
motion preferences persist. Discovery uses the same read-only Python services as the CLI and runs in workers.

Bootloader, legacy downloads, GSI tools and installation remain available through **Existing workflows**, or run
`curseofdroid-gui --classic`. QML pages still awaiting migration are visibly disabled. The existing installer is
early-development software; see [the audit and safety gaps](docs/DEVELOPMENT_ROADMAP.md) before using it.

See [the design system](docs/UI_DESIGN_SYSTEM.md) and [testing guide](docs/TESTING.md). Actual offscreen captures
(no injected devices) are in [docs/screenshots](docs/screenshots).

```bash
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.app --smoke-test
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture
```

## Platforms

CI runs the tests and real platform-tools downloads on Linux, Windows and macOS (Python 3.10 and 3.13).
Windows 10/11 and current macOS are supported; Windows 7/8/8.1 are not (no supported Python version).

## License

GPL-3.0-or-later.
