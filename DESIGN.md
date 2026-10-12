# Curse of Droid — design

A cross-platform desktop app (GUI + CLI) that takes an Android phone from stock to a custom ROM and custom
recovery: detect the device, install drivers/tools, check and (through the vendor's official procedure) unlock the
bootloader, find a matching ROM and recovery, download and verify them, flash them, and — if nothing prebuilt
exists and the user agrees — build one locally.

Status (2026-10-12): milestones 1–3 implemented (detection, catalog, verified downloads, sideload install + guard).

## 1. Goals and non-goals

**Goals**
- Windows, Linux, macOS from one code base.
- One guided flow for the common case; every step can also be run alone (CLI and GUI).
- Find official builds automatically: LineageOS, crDroid, Evolution X, PixelOS, DerpFest, AOSP/TrebleDroid GSIs;
  recoveries TWRP, OrangeFox, LineageOS Recovery (and the ROM's own recovery where a ROM ships one).
- Verify every download (publisher hash/signature) before it reaches the phone.
- Optional local build in a container, reusing the approach of the ATU-L21 project.
- Safe by default: explain each step, ask before anything destructive, keep a log the user can share.

**Non-goals (deliberate limits)**
- Bootloader unlocking only through the vendor's official mechanism (fastboot unlock, vendor unlock token/code,
  Mi Unlock authorization, Samsung "OEM unlocking"). No exploits, no EDL/BROM/test-point unlocking, no carrier-lock
  bypass, no FRP/Google-account or Mi-account lock bypass. A device the user can't unlock legitimately is reported as
  "not unlockable" with the reason.
- No writing of low-level partitions (bootloader, modem/radio, persist, EFS/modemst, oeminfo, NV data, xbl/abl,
  preloader, tz, keymaster/keystore partitions …). The flash planner works from an allowlist (§6).
- ClockworkMod is not offered: unmaintained since ~2015 and unable to install current ROMs. Listed as legacy with
  an explanation.

## 2. Architecture

```
            +------------------- UI layer -------------------+
            |  GUI (PySide6/Qt)        CLI (Typer/rich)      |
            +---------------------- core API ----------------+
            | session / workflow engine (steps, consent, log)|
  +---------+---------+-----------+-----------+-------------+------------+
  | transport         | device    | vendor    | catalog     | flasher    | builder
  | adb, fastboot,    | detection | unlock    | providers   | planner +  | container
  | heimdall, sideload| + profile | modules   | (ROM/recov.)| executors  | builds
  +-------------------+-----------+-----------+-------------+------------+
            | platform layer: tool bootstrap, drivers, udev, paths, downloads |
```

- **Language:** Python 3.11+. Packaged per OS with PyInstaller (single installer/AppImage/.app), plus `pipx install`.
- **GUI:** PySide6 (LGPL) — native look on all three platforms, threads for long operations.
- **CLI:** same core; `curseofdroid detect`, `curseofdroid unlock`, `curseofdroid find`, `curseofdroid install`, `curseofdroid build`.
- **Workflow engine:** every action is a `Step` with `check()` (already done?), `describe()` (plain-language text
  shown to the user), `risk` (none / data-loss / warranty / brick-risk), `run()`, `verify()`. Steps with risk need
  explicit consent; the GUI shows the exact commands that will run.
- **Plugins:** providers, vendor modules and flash strategies are registered entry points, so a new ROM or brand is
  one file plus a test.

## 3. Platform layer

| Item | Windows | Linux | macOS |
|---|---|---|---|
| adb/fastboot | Google platform-tools zip (`dl.google.com/android/repository/platform-tools-latest-windows.zip`), checksum-pinned, stored in the app data dir | same (`-linux.zip`) | same (`-darwin.zip`) |
| USB driver | Google USB Driver (Pixel/Android One and most fastboot devices), Xiaomi/Qualcomm ADB interface via the Google driver INF; Samsung USB driver for Samsung; installed with `pnputil` after a UAC prompt | not needed; installs udev rules (`51-android.rules`, user in `plugdev`) after asking for sudo | not needed |
| Samsung download mode | Heimdall (open source) where it supports the model; otherwise guided Odin instructions (Odin is proprietary and not redistributable) | Heimdall | Heimdall |

Driver check: after connecting, if Windows shows the device without a working driver (PnP query), offer the
matching driver. Never install unsigned drivers silently.

## 4. Device detection and profile

Sources, in order: `adb shell getprop` (Android or recovery), `fastboot getvar all`, Samsung download-mode info
(Heimdall `print-pit` read-only). Collected into a **DeviceProfile**:

- identity: brand, manufacturer, model, codename candidates (`ro.product.device`, `ro.build.product`,
  `ro.product.vendor.device`, fastboot `product`), market name
- state: bootloader locked/unlocked (`ro.boot.flash.locked`, `ro.boot.verifiedbootstate`, `getvar unlocked`),
  OEM-unlock allowed (`sys.oem_unlock_allowed`), battery level
- layout: A/B or A-only (`ro.build.ab_update`, `getvar slot-count`), dynamic partitions (`ro.boot.dynamic_partitions`,
  `getvar is-userspace`), system-as-root, Treble/VNDK version (`ro.treble.enabled`, `ro.vndk.version`),
  `vendor_boot` / `init_boot` presence, architecture
- stock firmware: Android version, security patch, build fingerprint

A **codename alias table** (community data, e.g. Xiaomi "lmi/lmipro", Samsung "a52q") maps the many names to the
codenames ROM projects use. The profile is shown to the user and saved with the log — serial numbers and IMEIs are
redacted from anything exported.

## 5. Bootloader: check and unlock (vendor modules)

Each vendor module implements `status()`, `requirements()` (what the user must do on the phone), `unlock()`.
Unlocking always wipes user data — the UI says so and asks twice.

| Vendor | Official procedure the module automates |
|---|---|
| Google Pixel / Android One / most AOSP-like | "OEM unlocking" in Developer options (checked via `sys.oem_unlock_allowed`), then `fastboot flashing unlock`; older devices `fastboot oem unlock` |
| OnePlus | same as above (+ older models `fastboot oem unlock`) |
| Motorola | `fastboot oem get_unlock_data` → user submits it on Motorola's unlock portal → enters the code → `fastboot oem unlock <code>`. Module formats the data and opens the portal; it does not scrape accounts |
| Xiaomi / Redmi / POCO | Mi account binding in Developer options + waiting period are enforced by Xiaomi. Module guides the binding, then performs the official unlock: Mi Unlock on Windows, or an open-source client that uses the same official authorization API with the user's own login (to evaluate: license, maintenance, ToS). Shows the remaining wait time |
| Samsung | "OEM unlocking" toggle → download mode → long-press unlock on the phone (Knox counter trips; warn). Exynos/Snapdragon US/CN carrier models that can't be unlocked are reported as such |
| Sony, Nokia/HMD, Huawei, others | Sony: unlock code from Sony's site; Nokia/HMD and Huawei: no current official program for most models → reported "not unlockable" |

Relocking is never done automatically: relocking with a non-stock OS can hard-brick many devices. Offered only for
devices with documented custom-AVB-key support (e.g. Pixel with ROMs that ship their key), with an explicit warning.

## 6. Flash planner

Input: DeviceProfile + chosen ROM/recovery package. Output: an ordered, human-readable plan of commands.

- Strategies: `recovery-sideload` (ROM zip via recovery, the common case for LineageOS/crDroid/EvoX/PixelOS),
  `fastboot-images` (factory-style image sets), `fastbootd` (dynamic partitions: system/vendor/product inside
  `super`), `gsi` (Treble GSI on top of stock vendor), `samsung-odin` (AP/BL/CP/CSC — only AP-equivalent parts;
  BL/CP never written), `recovery-image` (boot/recovery/vendor_boot/init_boot for the recovery itself).
- **Partition allowlist:** boot, init_boot, vendor_boot, recovery, dtbo, vbmeta (only with the ROM's own image, never
  disabling verification unless the ROM's instructions require it), system/vendor/product/system_ext/odm (inside
  super via fastbootd or as raw partitions on A-only), userdata/metadata (format only), cache. Anything else needs a
  per-device override shipped in the catalog *and* a separate confirmation. Firmware partitions: never.
- Pre-flight checks: battery ≥ 50 %, bootloader unlocked, package matches codename (zip's `updater-script`/
  `metadata` asserts), anti-rollback index where readable, enough free space, hash verified.
- Execution: one step at a time with read-back verification where possible (`getvar`, partition hash in recovery),
  stop on first error with a recovery hint (how to get back to fastboot/recovery).
- Slot handling for A/B: flash to the inactive slot or both as the ROM's instructions say; copy-partitions step
  when the ROM requires firmware on both slots (via the ROM's provided script only).

## 7. Catalog providers (ROMs and recoveries)

Each provider: `devices()` → codenames, `builds(codename)` → list of builds (version, date, Android version, size,
URL, hash, signature info, changelog URL, install-instructions URL). Results cached for a day.

| Project | Source of device/build data (to verify while implementing) |
|---|---|
| LineageOS | download API `download.lineageos.org/api/v2/devices/<codename>/builds`; device metadata from `LineageOS/hudson` and the wiki repo (also tells the required recovery and install method) |
| crDroid | `crdroidandroid/android_vendor_crDroidOTA` (per-version branch, `<codename>.json`) |
| Evolution X | `Evolution-X/OTA` (`builds/<codename>.json`) |
| PixelOS | `PixelOS-AOSP/official_devices` (devices + builds JSON) |
| DerpFest | official devices/OTA repo of DerpFest-AOSP (to locate) |
| AOSP GSI | TrebleDroid/phh GSI releases (GitHub releases) and Google's GSI page; used when no device ROM exists and the device is Treble |
| TWRP | `twrp.me` device pages (`TeamWin/twrpme` data) and `dl.twrp.me/<codename>/` |
| OrangeFox | OrangeFox API (`api.orangefox.download`) |
| LineageOS Recovery | shipped with each LineageOS build (`boot.img`/`recovery.img`) |

Matching: codename aliases, plus Android-version/firmware requirements read from the device's install page when the
project publishes them (e.g. "requires stock firmware X"). If a project's device list has the device but no build in
the last 6 months, show it as "unmaintained".

Downloads: resumable, mirror fallback, verify SHA-256/MD5 the project publishes; verify zip signatures where the
project signs builds (LineageOS). GApps are never bundled; the app links to the official MindTheGapps/NikGApps
pages and can patch known installer issues only with the user's file (as done for ATU-L21).

## 8. Builder (optional, with permission)

For devices with device trees but no recent build, or for a ROM the user wants that isn't published:

- Checks host resources first (disk ≥ 250 GB free, RAM ≥ 16 GB + swap, CPU cores) and explains the time cost.
- Container image with the AOSP build environment (Docker/Podman on Linux, Docker Desktop on Windows/macOS —
  macOS builds work but are slow; Windows via WSL2).
- Finds device/kernel/vendor repos from the ROM project's dependency files (`lineage.dependencies`,
  crDroid/EvoX manifests) and the codename; vendor blobs only from public `TheMuppets`-style repos or extracted from
  the user's own device/firmware (never redistributed by the tool).
- Fan/CPU-friendly mode (CPU quota + nice/ionice) — lessons from the ATU builds.

## 9. Safety, consent and logging

- Every destructive step: plain-language warning, list of what will be erased, explicit "I understand".
- Dry-run mode prints the full plan without touching the device.
- Session log (commands, outputs, hashes) saved locally; export redacts serials, IMEIs, account IDs.
- Never stores account passwords; vendor portals open in the user's browser.
- Telemetry: none.

## 10. Repository layout (planned)

```
curseofdroid/
  curseofdroid/
    core/        workflow engine, steps, consent, logging
    platform/    tool bootstrap, drivers, udev, downloads
    transport/   adb, fastboot, heimdall wrappers
    device/      detection, profile, codename aliases
    vendors/     google.py, oneplus.py, motorola.py, xiaomi.py, samsung.py, generic.py
    catalog/     lineageos.py, crdroid.py, evolutionx.py, pixelos.py, derpfest.py, gsi.py, twrp.py, orangefox.py
    flash/       planner.py, strategies/*.py, allowlist.py
    builder/     container build orchestration
    gui/         PySide6 app
    cli.py
  data/          codename aliases, partition allowlist overrides
  tests/         unit tests + recorded getprop/getvar fixtures per device
  docs/
```

## 11. Milestones

1. **M1 — core + detection:** platform-tools bootstrap, adb/fastboot transport, DeviceProfile, CLI `detect`.
   Fixtures from ATU-L21 (A-only, Treble 8.0) and at least one A/B + dynamic-partitions device.
2. **M2 — catalog:** LineageOS + TWRP + OrangeFox providers, `find`, verified downloads.
3. **M3 — flash:** planner, recovery-sideload and fastboot strategies, dry-run, `install` for Pixel/OnePlus/generic.
4. **M4 — vendors:** Google/OnePlus/Motorola unlock flows, Xiaomi guided flow, Samsung/Heimdall.
5. **M5 — GUI** over the same core.
6. **M6 — more ROMs** (crDroid, EvoX, PixelOS, DerpFest, GSIs).
7. **M7 — builder.**
8. Packaging + CI (GitHub Actions builds for all three OSes).

## 12. Open questions

- ~~Project name~~: Curse of Droid (repository `Curse-of-Droid`).
- License: GPL-3.0 (compatible with PySide6 LGPL and Heimdall MIT) is the default proposal.
- Xiaomi: which unlock client (official Windows tool vs. open-source client) — decide after reviewing licenses.
- Test devices available besides ATU-L21.
