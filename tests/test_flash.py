import zipfile

import pytest

from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash.executor import Executor, StepFailed, validate
from curseofdroid.flash.guard import GuardError, check_command
from curseofdroid.flash.package import inspect
from curseofdroid.flash.plan import Command, Plan, Step
from curseofdroid.flash.planner import InstallRequest, PlanError, plan_sideload_install
from curseofdroid.transport.base import Result


# ---- guard -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["flash", "boot", "x.img"], ["flash", "boot_b", "x.img"], ["flash", "recovery", "r.img"],
    ["flash", "vendor_boot", "v.img"], ["erase", "userdata"], ["format:ext4", "cache"], ["-w"],
    ["boot", "twrp.img"], ["getvar", "all"], ["reboot", "recovery"], ["-s", "SER", "flash", "dtbo", "d.img"],
])
def test_guard_allows_install_commands(args):
    check_command("fastboot", args)


@pytest.mark.parametrize("args, why", [
    (["flashing", "lock"], "relock"), (["oem", "lock"], "relock"), (["OEM", "RELOCK"], "relock"),
    (["flashing", "lock_critical"], "relock"), (["flash", "modem", "m.img"], "firmware"),
    (["flash", "abl_a", "a.img"], "firmware"), (["flash", "persist", "p.img"], "firmware"),
    (["flash", "xloader", "x"], "firmware"), (["flash", "oeminfo", "o"], "firmware"),
    (["erase", "boot"], "only userdata"), (["erase", "modemst1"], "only userdata"),
    (["flashall"], "every image"), (["update", "image.zip"], "every image"),
    (["flash", "system", "s.img"], "logical"), (["--disable-verity", "flash", "vbmeta", "v.img"], "verified boot"),
    (["flash", "something_new", "x"], "allowlist"), (["flash"], "without a partition"),
])
def test_guard_refuses(args, why):
    with pytest.raises(GuardError, match=why):
        check_command("fastboot", args)


def test_guard_logical_partitions():
    check_command("fastboot", ["flash", "system", "s.img"], fastbootd=True)
    check_command("fastboot", ["flash", "system", "s.img"], logical_ok=True)  # A-only device: real partition


def test_guard_adb_raw_writes():
    check_command("adb", ["shell", "dd if=/tmp/x of=/dev/block/bootdevice/by-name/system bs=4M"])
    check_command("adb", ["sideload", "rom.zip"])
    with pytest.raises(GuardError):
        check_command("adb", ["shell", "dd if=/tmp/x of=/dev/block/mmcblk0p54"])
    with pytest.raises(GuardError):
        check_command("adb", ["shell", "dd if=/tmp/x of=/dev/block/by-name/modem"])
    with pytest.raises(GuardError):
        check_command("adb", ["shell", "mkfs.f2fs /dev/block/by-name/persist"])
    check_command("adb", ["shell", "mkfs.f2fs /dev/block/by-name/userdata"])


# ---- package -----------------------------------------------------------------------------------------------

def make_zip(tmp_path, name, files):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in files.items():
            z.writestr(n, data)
    return p


def test_package_metadata_and_updater_script(tmp_path):
    ab = make_zip(tmp_path, "ab.zip", {"payload.bin": b"x",
                                       "META-INF/com/android/metadata": "ota-type=AB\npre-device=lavender,lavender2\n"})
    info = inspect(ab)
    assert info.ab_payload and info.devices == ["lavender", "lavender2"]
    assert info.matches(["lavender"]) is True and info.matches(["oriole"]) is False
    legacy = make_zip(tmp_path, "l.zip", {
        "META-INF/com/google/android/update-binary": "#!",
        "META-INF/com/google/android/updater-script":
            'assert(getprop("ro.product.device") == "mido" || getprop("ro.build.product") == "mido");'})
    assert inspect(legacy).devices == ["mido"]
    plain = make_zip(tmp_path, "p.zip", {"readme.txt": "hi"})
    assert inspect(plain).kind == "unknown" and inspect(plain).matches(["x"]) is None


# ---- planner -----------------------------------------------------------------------------------------------

def profile(**kw):
    base = dict(mode="android", brand="Xiaomi", model="Redmi Note 7", codenames=["lavender"],
                bootloader_unlocked="yes", battery_percent=80)
    base.update(kw)
    return DeviceProfile(**base)


@pytest.fixture
def rom(tmp_path):
    return inspect(make_zip(tmp_path, "rom.zip", {"payload.bin": b"x",
                                                   "META-INF/com/android/metadata": "pre-device=lavender\n"}))


def test_plan_boots_recovery_temporarily_and_wipes(rom, tmp_path):
    rec = tmp_path / "twrp.img"
    rec.write_bytes(b"x")
    plan = plan_sideload_install(profile(), InstallRequest(rom, recovery=rec, recovery_name="TWRP"))
    titles = [s.title for s in plan.steps]
    assert titles[0] == "Reboot to fastboot"
    assert any(c.args[:1] == ["boot"] for s in plan.steps for c in s.commands)  # not written
    assert any(s.risk == "data-loss" for s in plan.steps)
    assert plan.steps[-1].wait_for == "android" and plan.steps[-1].wait_timeout >= 600
    validate(plan)
    assert "rom.zip" in plan.render()


@pytest.mark.parametrize("kw, msg", [
    (dict(bootloader_unlocked="no"), "locked"), (dict(battery_percent=20), "battery"),
    (dict(codenames=["oriole"]), "built for lavender"),
])
def test_preflight_blocks(rom, kw, msg):
    with pytest.raises(PlanError, match=msg):
        plan_sideload_install(profile(**kw), InstallRequest(rom))


# ---- executor ----------------------------------------------------------------------------------------------

class FakeUI:
    def __init__(self, consent=True):
        self.consent, self.log = consent, []

    def info(self, t):
        self.log.append(t)

    def confirm(self, step):
        return self.consent

    def manual(self, step):
        return True


def runner_for(modes):
    """modes: list of adb states returned by successive `adb devices` calls"""
    calls, it = [], iter(modes)

    def run(args, timeout):
        calls.append(args)
        if args[1:] == ["devices", "-l"]:
            state = next(it, modes[-1])
            return Result(args, 0, f"List of devices attached\nS1 {state} usb:1\n" if state else "", "")
        if args[1:] == ["devices"]:
            return Result(args, 0, "", "")
        return Result(args, 0, "", "")
    run.calls = calls
    return run


def test_executor_rejects_whole_plan_before_running():
    bad = Plan("x", [Step("ok", "", commands=[Command("adb", ["reboot", "bootloader"])]),
                     Step("bad", "", "system-write", [Command("fastboot", ["flash", "modem", "m.img"])])])
    r = runner_for(["device"])
    with pytest.raises(StepFailed, match="plan rejected"):
        Executor("adb", "fastboot", None, FakeUI(), r, sleep=lambda s: None).run(bad)
    assert r.calls == []  # nothing ran, not even the harmless reboot


def test_executor_stops_without_consent():
    plan = Plan("x", [Step("wipe", "", "data-loss", [Command("fastboot", ["erase", "userdata"])])])
    r = runner_for(["device"])
    with pytest.raises(StepFailed, match="cancelled"):
        Executor("adb", "fastboot", None, FakeUI(consent=False), r, sleep=lambda s: None).run(plan)
    assert r.calls == []


def test_executor_waits_for_mode():
    plan = Plan("x", [Step("reboot", "", "reboot", [Command("adb", ["reboot", "recovery"])], wait_for="recovery")])
    r = runner_for(["", "", "recovery"])
    Executor("adb", "fastboot", None, FakeUI(), r, sleep=lambda s: None).run(plan)
    assert ["adb", "reboot", "recovery"] in r.calls


@pytest.mark.parametrize("args, why", [
    (["format:ext4", "persist"], "only userdata"), (["flash:raw", "modem", "k"], "firmware"),
    (["oem", "frp-unlock"], "unknown"), (["oem", "erase-all"], "unknown"), (["flashing", "unlock"], "vendor unlock"),
    (["--slot=all", "flash", "xbl", "x"], "firmware"), (["--skip-reboot"], "without a sub-command"),
])
def test_guard_refuses_bypasses(args, why):
    with pytest.raises(GuardError, match=why):
        check_command("fastboot", args)


def test_guard_unlock_only_when_allowed():
    check_command("fastboot", ["flashing", "unlock"], allow_unlock=True)
    check_command("fastboot", ["oem", "get_unlock_data"], allow_unlock=True)
    with pytest.raises(GuardError):
        check_command("fastboot", ["flashing", "lock"], allow_unlock=True)
    check_command("fastboot", ["--set-active=b"])
    check_command("fastboot", ["--slot=all", "flash", "boot", "b.img"])


def test_gsi_plan_dynamic_uses_fastbootd(tmp_path):
    from curseofdroid.flash.planner import plan_gsi_install
    img = tmp_path / "system.img"
    img.write_bytes(b"x")
    p = profile(dynamic_partitions="yes", mode="android")
    plan = plan_gsi_install(p, img)
    validate(plan)
    flash = [s for s in plan.steps if any(c.args[:2] == ["flash", "system"] for c in s.commands)][0]
    assert flash.fastbootd and any(s.wait_for == "fastbootd" for s in plan.steps)
    assert not any("vbmeta" in " ".join(c.args) for s in plan.steps for c in s.commands)


def test_gsi_plan_legacy_writes_real_system(tmp_path):
    from curseofdroid.flash.planner import plan_gsi_install
    img = tmp_path / "system.img"
    img.write_bytes(b"x")
    plan = plan_gsi_install(profile(dynamic_partitions="no", mode="fastboot"), img)
    validate(plan)
    assert not any(s.wait_for == "fastbootd" for s in plan.steps)
    with pytest.raises(PlanError, match="unpack"):
        plan_gsi_install(profile(), tmp_path / "system.img.xz")
