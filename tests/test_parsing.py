from pathlib import Path

from curseofdroid.device.profile import from_fastboot, from_props
from curseofdroid.transport.adb import parse_devices, parse_getprop
from curseofdroid.transport.fastboot import parse_devices as fb_devices, parse_getvar_all

FIX = Path(__file__).parent / "fixtures"


def test_adb_devices():
    text = ("List of devices attached\n"
            "SER1AL device usb:1-1 product:atu_l21 model:ATU_L21 device:atu_l21 transport_id:1\n"
            "ZY22 recovery usb:1-2 transport_id:2\n"
            "emu unauthorized usb:1-3 transport_id:3\n")
    devs = parse_devices(text)
    assert [(d.serial, d.state) for d in devs] == [("SER1AL", "device"), ("ZY22", "recovery"),
                                                   ("emu", "unauthorized")]
    assert devs[0].info["model"] == "ATU_L21"


def test_getprop_empty_values():
    props = parse_getprop((FIX / "huawei_atu_l21_lineage17_getprop.txt").read_text())
    assert props["persist.sys.empty"] == ""
    assert props["ro.product.model"] == "ATU-L21"


def test_profile_a_only_treble_huawei():
    props = parse_getprop((FIX / "huawei_atu_l21_lineage17_getprop.txt").read_text())
    p = from_props(props)
    assert p.brand == "HUAWEI" and p.model == "ATU-L21"
    # hardware codename (vendor) first, ROM's device name kept as alias
    assert p.codenames == ["msm8937_64", "atu_l21"]  # board "msm8937" is not a codename
    # Huawei reports flash.locked=1/green even when unlocked; ro.userlock is right
    assert p.bootloader_unlocked == "yes"
    # ro.build.ab_update=true comes from the A/B-built GSI system; no slot suffix = A-only
    assert p.ab == "no" and p.treble == "yes" and p.vndk_version == "26"
    assert p.sdk == 29 and p.system_as_root == "no"
    assert p.to_dict()["serial"] == "AB…89"


def test_lock_state_sources():
    assert from_props({"ro.boot.vbmeta.device_state": "unlocked", "ro.boot.flash.locked": "1"}).bootloader_unlocked == "yes"
    assert from_props({"ro.boot.verifiedbootstate": "orange"}).bootloader_unlocked == "yes"
    assert from_props({"ro.boot.verifiedbootstate": "yellow"}).bootloader_unlocked == "no"
    assert from_props({"ro.boot.slot_suffix": "_b", "ro.build.version.sdk": "34"}).current_slot == "b"


def test_fastboot_devices():
    assert fb_devices("1A2B3C\tfastboot\nZZ\tfastbootd\n") == [("1A2B3C", "fastboot"), ("ZZ", "fastbootd")]


def test_getvar_composite_keys_and_empty_values():
    v = parse_getvar_all((FIX / "pixel_ab_dynamic_getvar.txt").read_text())
    assert v["partition-size:super"] == "0x220000000"
    assert v["partition-type:boot_a"] == "raw"
    assert v["device-state"] == ""
    assert v["product"] == "oriole"  # "(bootloader) cpu-abi:arm64-v8a" (no space) is skipped, not fatal
    assert "Finished" not in "".join(v)


def test_profile_from_fastboot_ab():
    p = from_fastboot(parse_getvar_all((FIX / "pixel_ab_dynamic_getvar.txt").read_text()))
    assert p.codename == "oriole"
    assert p.bootloader_unlocked == "yes"
    assert p.ab == "yes" and p.current_slot == "a"
    assert p.mode == "fastboot"
    assert p.battery_percent == 87
    assert p.dynamic_partitions == "yes"


def test_fastbootd_mode_and_locked_device_state():
    p = from_fastboot({"product": "x", "is-userspace": "yes", "device-state": "locked", "slot-count": "1"})
    assert p.mode == "fastbootd" and p.bootloader_unlocked == "no" and p.ab == "no"


def test_merge_keeps_known_values():
    a = from_props({"ro.product.device": "atu_l21", "ro.boot.flash.locked": "0"})
    b = from_fastboot({"product": "ATU-L21", "slot-count": "1"})
    a.merge(b)
    assert a.codenames == ["atu_l21", "ATU-L21"] and a.ab == "no" and a.bootloader_unlocked == "yes"


def test_profile_oppo_virtual_ab_locked():
    p = from_props(parse_getprop((FIX / "oppo_cph2801_android16_getprop.txt").read_text()))
    assert p.market_name == "OPPO Reno15 F 5G" and p.soc == "QTI SM6450"
    assert p.codenames == ["OP628FL1", "CPH2801TR"]  # not the "parrot" platform
    assert p.bootloader_unlocked == "no" and p.ab == "yes" and p.current_slot == "b"
    assert p.dynamic_partitions == "yes" and p.virtual_ab == "yes"
    assert p.boot_partitions == ["init_boot", "vendor_boot"]
