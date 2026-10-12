from curseofdroid.device.detect import detect
from curseofdroid.transport.base import Result


def fake_runner(responses):
    calls = []

    def run(args, timeout):
        calls.append(args)
        key = " ".join(args[1:])
        out, err = responses.get(key, ("", ""))
        return Result(list(args), 0, out, err)

    run.calls = calls
    return run


def test_detect_android_unauthorized_and_fastboot():
    r = fake_runner({
        "devices -l": ("List of devices attached\nAAA device usb:1 model:X\nBBB unauthorized usb:2\n", ""),
        "-s AAA shell getprop": ("[ro.product.device]: [lmi]\n[ro.boot.flash.locked]: [1]\n", ""),
        "-s AAA shell cat /sys/class/power_supply/battery/capacity 2>/dev/null || dumpsys battery 2>/dev/null":
            ("64\n", ""),
        "devices": ("CCC\tfastboot\n", ""),
        "-s CCC getvar all": ("", "(bootloader) product: oriole\n(bootloader) unlocked: no\n"),
    })
    found = detect("adb", "fastboot", r)
    assert [(d.serial, d.mode) for d in found] == [("AAA", "android"), ("BBB", "android"), ("CCC", "fastboot")]
    assert found[0].profile.codename == "lmi" and found[0].profile.bootloader_unlocked == "no"
    assert found[0].profile.battery_percent == 64
    assert "unauthorized" in found[1].problem and found[1].profile is None
    assert found[2].profile.codename == "oriole" and found[2].profile.bootloader_unlocked == "no"
    # detection is read-only: no flash/erase/reboot/unlock commands
    assert not [c for c in r.calls if set(c) & {"flash", "erase", "reboot", "flashing", "oem", "format"}]
