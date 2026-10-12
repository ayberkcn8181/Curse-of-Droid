from pathlib import Path

import pytest

from curseofdroid.device.profile import DeviceProfile, from_props
from curseofdroid.flash.executor import Executor, validate
from curseofdroid.flash.guard import GuardError, check_command
from curseofdroid.platform.drivers import udev_rules
from curseofdroid.transport.adb import parse_getprop
from curseofdroid.vendors import vendor_for

FIX = Path(__file__).parent / "fixtures"


def real(name):
    return from_props(parse_getprop((FIX / name).read_text()))


def test_oppo_has_no_official_method_but_is_not_called_unlockable():
    p = real("oppo_cph2801_android16_getprop.txt")
    info = vendor_for(p).info(p)
    assert not info.official
    s = info.summary()
    assert "no official unlock method" in s and "detects it" in s
    assert "can't be unlocked" not in s and "cannot be unlocked" not in s


def test_huawei_profile_maps_to_huawei():
    p = real("huawei_atu_l21_lineage17_getprop.txt")
    assert vendor_for(p).name.startswith("Huawei")


@pytest.mark.parametrize("brand, official, automated", [
    ("google", True, True), ("OnePlus", True, True), ("motorola", True, True), ("Xiaomi", True, False),
    ("POCO", True, False), ("samsung", True, False), ("realme", False, False), ("Sony", True, False),
    ("Fairbrand", False, False),
])
def test_vendor_table(brand, official, automated):
    info = vendor_for(DeviceProfile(brand=brand)).info(DeviceProfile(brand=brand))
    assert (info.official, info.automated) == (official, automated)


def test_pixel_unlock_plan_passes_guard_only_as_unlock_step():
    p = DeviceProfile(mode="android", brand="google", model="Pixel 6", codenames=["oriole"],
                      bootloader_unlocked="no", oem_unlock_allowed="no")
    plan = vendor_for(p).unlock_plan(p)
    validate(plan)
    unlock = [s for s in plan.steps if s.unlock]
    assert unlock and unlock[0].risk == "data-loss"
    assert plan.steps[0].title == "Allow OEM unlocking"  # toggle still off
    with pytest.raises(GuardError):  # the same command outside an unlock step is refused
        check_command("fastboot", unlock[0].commands[0].args)


def test_motorola_code_is_asked_and_validated():
    p = DeviceProfile(mode="fastboot", brand="motorola", model="g", oem_unlock_allowed="yes")
    plan = vendor_for(p).unlock_plan(p)
    validate(plan)

    class UI:
        answers = iter(["ABCDEF123456"])

        def info(self, t): pass
        def confirm(self, s): return True
        def manual(self, s): return True
        def ask(self, s): return next(self.answers)

    calls = []

    def run(args, timeout):
        from curseofdroid.transport.base import Result
        calls.append(args)
        return Result(args, 0, "", "(bootloader) unlocked: yes" if "getvar" in args else "")

    Executor("adb", "fastboot", None, UI(), run, sleep=lambda s: None).run(plan)
    assert ["fastboot", "oem", "unlock", "ABCDEF123456"] in calls


def test_motorola_rejects_injected_answer():
    p = DeviceProfile(mode="fastboot", brand="motorola", oem_unlock_allowed="yes")
    plan = vendor_for(p).unlock_plan(p)

    class UI:
        def info(self, t): pass
        def confirm(self, s): return True
        def manual(self, s): return True
        def ask(self, s): return "X; fastboot flashing lock"

    from curseofdroid.flash.executor import StepFailed
    from curseofdroid.transport.base import Result
    with pytest.raises(StepFailed, match="no valid answer"):
        Executor("adb", "fastboot", None, UI(), lambda a, t: Result(a, 0, "", ""), sleep=lambda s: None).run(plan)


def test_udev_rules_cover_major_vendors():
    rules = udev_rules()
    for vid in ("18d1", "04e8", "2717", "22d9", "12d1"):
        assert f'ATTR{{idVendor}}=="{vid}"' in rules
    assert 'TAG+="uaccess"' in rules
