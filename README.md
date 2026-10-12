# romtool (working name)

Install custom ROMs and custom recoveries on Android phones — on Windows, Linux and macOS.
romtool detects the phone, sets up adb/fastboot and drivers, checks the bootloader and unlocks it through the
vendor's official procedure, finds a matching ROM (LineageOS, crDroid, Evolution X, PixelOS, DerpFest, GSIs) and
recovery (TWRP, OrangeFox, LineageOS Recovery), verifies the downloads and flashes them — asking before every
destructive step. If no build exists it can, with your permission, build one locally.

**Status: early development (milestone 1: tool setup + device detection).** Nothing here flashes a phone yet.
See [DESIGN.md](DESIGN.md) for the plan and the deliberate limits (official unlock methods only, firmware
partitions are never written).

## Try it

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/romtool tools install   # downloads Google's platform-tools into romtool's data directory
.venv/bin/romtool detect          # Android (USB debugging), recovery, fastboot or fastbootd
.venv/bin/romtool detect --json
```

Detection is read-only. Serial numbers are shortened in the output unless `--show-serial` is given.

## License

GPL-3.0-or-later.
