"""Plan-boundary regressions. No adb/fastboot executable or real device is used."""

import pytest

from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash.executor import Executor, StepFailed, validate
from curseofdroid.flash.guard import GuardError, check_command
from curseofdroid.flash.plan import Command, InstallTarget, Plan, Step
from curseofdroid.transport.base import Result
from curseofdroid.vendors import vendor_for


# These unrecognized ADB operations previously fell through the shell blocklist.
ADB_REJECTED = [
    ["shell", "rm -rf /data"],
    ["shell", "sh", "-c", "echo overwritten >/dev/block/by-name/modem"],
    ["shell", "toybox", "dd", "if=/tmp/x", "of=/dev/block/by-name/modem"],
    ["shell", "dd if=/tmp/x of=/dev/block/by-name/system; reboot"],
    ["shell", "dd if=/tmp/x of=/dev/block/by-name/system of=/dev/block/by-name/modem"],
    ["shell", "dd if=/tmp/x of=/dev/block/by-name/system/../../modem"],
    ["shell", "mkfs.f2fs /dev/block/by-name/userdata; reboot"],
    ["shell", "getprop"],
    ["exec-out", "sh", "-c", "id"],
    ["exec-in", "sh"],
    ["push", "payload", "/dev/block/by-name/modem"],
    ["sync"],
    ["restore", "backup.ab"],
    ["install", "app.apk"],
    ["root"],
    ["remount"],
    ["disable-verity"],
    ["reboot", "edl"],
    ["reboot", "download"],
    ["reboot", "recovery; reboot"],
    ["reboot", "bootloader", "shell", "id"],
    ["sideload", "rom.zip", "reboot"],
    ["sideload", "--exit-on-write-error"],
    ["devices", "-l", "shell", "id"],
    ["get-state", "reboot"],
]


FASTBOOT_REJECTED = [
    ["--unknown", "flash", "boot", "boot.img"],
    ["--force", "flash", "boot", "boot.img"],
    ["--unbuffered", "flash", "boot", "boot.img"],
    ["--slot=all", "--slot=a", "flash", "boot", "boot.img"],
    ["--slot=../../modem", "flash", "boot", "boot.img"],
    ["--slot", "--force", "flash", "boot", "boot.img"],
    ["--slot=a", "reboot"],
    ["--skip-reboot", "--skip-reboot", "-w"],
    ["--skip-reboot", "oem", "unlock"],
    ["flash", "boot", "boot.img", "--force"],
    ["flash", "boot", "boot.img", "flash", "modem", "modem.img"],
    ["flash", "boot", "--force"],
    ["flash", "boot", "-"],
    ["flash", "boot"],
    ["flash:raw", "boot", "kernel.img", "ramdisk.img"],
    ["erase", "userdata", "erase", "modem"],
    ["erase", "userdata", "--slot=all"],
    ["format:ext4", "userdata", "flash", "modem", "modem.img"],
    ["format:ext4:4096", "userdata"],
    ["format:unknown", "userdata"],
    ["-w", "flash", "modem", "modem.img"],
    ["boot", "recovery.img", "flash", "modem", "modem.img"],
    ["boot", "--skip-reboot"],
    ["boot"],
    ["reboot", "bootloader", "flash", "modem", "modem.img"],
    ["reboot", "edl"],
    ["reboot", "download"],
    ["reboot-bootloader", "flash", "modem", "modem.img"],
    ["continue", "erase", "modem"],
    ["getvar", "all", "erase", "modem"],
    ["getvar", "--slot=all"],
    ["getvar", "-w"],
    ["getvar", "--force"],
    ["getvar", "-s"],
    ["getvar", "all; reboot"],
    ["devices", "-l", "flash", "modem", "modem.img"],
    ["set_active", "a", "flash", "modem", "modem.img"],
    ["set_active", "all"],
    ["set_active", "../../modem"],
    ["--set-active=all"],
    ["--set-active=b", "erase", "modem"],
    ["--set-active-unknown=b"],
    ["--set-active", "a", "erase", "modem"],
    ["flashing", "unlock", "erase", "modem"],
    ["oem", "get_unlock_data", "erase", "modem"],
    ["oem", "unlock", "CODE", "erase", "modem"],
    ["oem", "unlock", "--force"],
    ["oem", "unlock", "CODE; reboot"],
    ["oem", "unlock", "CODE WITH SPACE"],
    ["oem", "unlock", "{answer}"],
    ["oem", "unlock", "ＣＯＤＥ"],
    ["FLASH", "boot", "boot.img"],
    ["--disable-verity", "flash", "vbmeta", "vbmeta.img"],
    ["flash", "vbmeta", "vbmeta.img", "--disable-verification=false"],
    ["flashing", "lock"],
    ["oem", "relock"],
    ["flashing", "unlock_critical"],
]


@pytest.mark.parametrize("args", ADB_REJECTED)
def test_adb_plan_commands_fail_closed(args):
    with pytest.raises(GuardError):
        check_command("adb", args, allow_unlock=True)


@pytest.mark.parametrize("args", FASTBOOT_REJECTED)
def test_fastboot_rejects_unknown_options_and_unchecked_tails(args):
    # Even a vendor unlock step cannot permit arbitrary tails or global options.
    with pytest.raises(GuardError):
        check_command("fastboot", args, fastbootd=True, allow_unlock=True)


@pytest.mark.parametrize("tool,args", [
    ("adb", ["reboot"]),
    ("adb", ["reboot", "recovery"]),
    ("adb", ["reboot", "bootloader"]),
    ("adb", ["reboot", "fastboot"]),
    ("adb", ["sideload", "/tmp/ROM files/rom.zip"]),
    ("adb", ["sideload", r"C:\ROM files\rom.zip"]),
    ("adb", ["devices", "-l"]),
    ("adb", ["get-state"]),
    ("adb", ["get-serialno"]),
    ("adb", ["-s", "[::1]:5555", "reboot", "recovery"]),
    ("adb", ["-t", "12", "reboot", "bootloader"]),
    ("fastboot", ["-s", "SERIAL-123", "flash", "boot_a", "/tmp/ROM files/boot.img"]),
    ("fastboot", ["--slot", "b", "flash", "boot", "boot.img"]),
    ("fastboot", ["--slot=all", "--skip-reboot", "flash", "boot", r"C:\ROM files\boot.img"]),
    ("fastboot", ["format:f2fs", "userdata"]),
    ("fastboot", ["erase", "metadata"]),
    ("fastboot", ["--skip-reboot", "-w"]),
    ("fastboot", ["--set-active", "a"]),
    ("fastboot", ["set_active", "b"]),
    ("fastboot", ["reboot", "fastboot"]),
    ("fastboot", ["reboot-bootloader"]),
    ("fastboot", ["reboot-recovery"]),
    ("fastboot", ["reboot-fastboot"]),
    ("fastboot", ["continue"]),
    ("fastboot", ["getvar", "partition-size:system"]),
    ("fastboot", ["devices", "-l"]),
])
def test_supported_plan_commands_keep_literal_host_paths(tool, args):
    check_command(tool, args)


@pytest.mark.parametrize("tool,args", [
    ("adb", []),
    ("fastboot", []),
    ("adb", [""]),
    ("adb", ["", "reboot"]),
    ("adb", ["reboot", ""]),
    ("fastboot", ["flash", "", "boot.img"]),
    ("fastboot", ["flash", "boot", ""]),
    ("fastboot", ["boot", "   "]),
    ("adb", ["reboot", None]),
    ("fastboot", ["flash", "boot", 12]),
    ("adb", ["reboot", "recovery\n"]),
    ("fastboot", ["boot", "boot.img\0"]),
    ("fastboot", ["boot", "boot.img\r"]),
    ("fastboot", ["boot", "boot.img\x7f"]),
    ("adb", ["-s"]),
    ("adb", ["-s", "--reboot", "reboot"]),
    ("fastboot", ["-s", "", "reboot"]),
    ("adb", ["-t", "bad", "reboot"]),
    ("adb", ["-t", "0", "reboot"]),
    ("fastboot", ["-t", "1", "reboot"]),
    ("adb", ["-s", "SER", "-s", "OTHER", "reboot"]),
    ("adb", ["-s", "SER", "-t", "1", "reboot"]),
    ("fastboot", ["-s", "SER", "-s", "OTHER", "reboot"]),
    ("fastboot", ["-s", "SER"]),
    ("adb", "reboot"),
    ("fastboot", b"reboot"),
    ("adb", None),
    ("heimdall", ["flash"]),
])
def test_malformed_argv_and_selectors_are_rejected(tool, args):
    with pytest.raises(GuardError):
        check_command(tool, args)


@pytest.mark.parametrize("args", [
    ["flashing", "unlock"],
    ["oem", "unlock"],
    ["oem", "unlock", "ABCDEF123456"],
    ["oem", "unlock", "0xABC123"],
    ["oem", "get_unlock_data"],
    ["oem", "device-info"],
    ["flashing", "get_unlock_ability"],
])
def test_vendor_commands_require_explicit_unlock_context(args):
    with pytest.raises(GuardError, match="vendor unlock flow"):
        check_command("fastboot", args)
    check_command("fastboot", args, allow_unlock=True)


@pytest.mark.parametrize("brand", ["Google", "OnePlus", "Nothing", "Motorola", "Other"])
def test_current_automated_vendor_plans_pass_preflight(brand):
    profile = DeviceProfile(mode="android", brand=brand, model="test",
                            bootloader_unlocked="no", oem_unlock_allowed="yes")
    plan = vendor_for(profile).unlock_plan(profile)
    assert plan is not None
    validate(plan)


class QuietUI:
    def info(self, text):
        pass

    def confirm(self, step):
        return True

    def manual(self, step):
        return True

    def ask(self, step):
        return "CODE123"


@pytest.mark.parametrize("tool,args", [
    ("adb", ADB_REJECTED[0]),
    ("adb", ADB_REJECTED[3]),
    ("adb", ["push", "x", "/dev/block/by-name/modem"]),
    ("fastboot", ["reboot", "bootloader", "flash", "modem", "m.img"]),
    ("fastboot", ["-w", "flash", "modem", "m.img"]),
    ("fastboot", ["--force", "flash", "boot", "b.img"]),
    ("fastboot", ["getvar", "-w"]),
    ("fastboot", ["oem", "unlock", "CODE", "erase", "modem"]),
])
def test_invalid_later_step_rejects_entire_plan_before_any_runner_call(tool, args):
    calls = []

    def runner(argv, timeout):
        calls.append(list(argv))
        return Result(list(argv), 0, "", "")

    plan = Plan("test", [
        Step("earlier", "", commands=[Command("adb", ["reboot", "recovery"])]),
        Step("invalid", "", "data-loss", [Command(tool, args)], unlock=True),
    ])
    with pytest.raises(StepFailed, match="plan rejected"):
        Executor("adb", "fastboot", "SERIAL", QuietUI(), runner).run(plan)
    assert calls == []


def test_changed_command_is_rechecked_and_reported_before_transport():
    calls = []
    command = Command("fastboot", ["erase", "userdata"])
    plan = Plan("test", [Step("write", "", "data-loss", [command])],
                target=InstallTarget("SERIAL", ("lavender",), "no", "", "no"))

    class ChangingUI(QuietUI):
        def confirm(self, step):
            command.args = ["erase", "modem"]
            return True

    def runner(argv, timeout):
        calls.append(list(argv))
        return Result(list(argv), 0, "", "")

    with pytest.raises(StepFailed, match="command rejected"):
        Executor("adb", "fastboot", "SERIAL", ChangingUI(), runner).run(plan)
    assert calls == []


def test_unresolved_unlock_code_only_allowed_for_an_asked_plan():
    args = ["oem", "unlock", "{answer}"]
    with pytest.raises(GuardError, match="invalid vendor unlock code"):
        check_command("fastboot", args, allow_unlock=True)
    check_command("fastboot", args, allow_unlock=True, allow_unlock_placeholder=True)
    plan = Plan("test", [Step("unlock", "", "data-loss", [Command("fastboot", args)], unlock=True)])
    with pytest.raises(GuardError, match="invalid vendor unlock code"):
        validate(plan)


@pytest.mark.parametrize("answer", ["ＣＯＤＥ", "CODE;reboot", "--force", "", "A" * 129])
def test_invalid_unlock_answers_never_reach_transport(answer):
    # Use the real Motorola plan, retaining only the question step so read-only
    # unlock-data retrieval cannot obscure the assertion about zero runner calls.
    profile = DeviceProfile(mode="fastboot", brand="Motorola", oem_unlock_allowed="yes")
    unlock = next(step for step in vendor_for(profile).unlock_plan(profile).steps if step.ask)
    calls = []

    class AnswerUI(QuietUI):
        def ask(self, step):
            return answer

    def runner(argv, timeout):
        calls.append(list(argv))
        return Result(list(argv), 0, "", "")

    with pytest.raises(StepFailed, match="no valid answer|command rejected"):
        Executor("adb", "fastboot", "SERIAL", AnswerUI(), runner).run(Plan("test", [unlock]))
    assert calls == []


def test_valid_motorola_code_is_substituted_and_sent_as_one_argument():
    profile = DeviceProfile(mode="fastboot", brand="Motorola", oem_unlock_allowed="yes")
    unlock = next(step for step in vendor_for(profile).unlock_plan(profile).steps if step.ask)
    calls = []

    def runner(argv, timeout):
        calls.append(list(argv))
        return Result(list(argv), 0, "", "")

    Executor("adb", "fastboot", "SERIAL", QuietUI(), runner).run(Plan("test", [unlock]))
    assert calls == [["fastboot", "-s", "SERIAL", "oem", "unlock", "CODE123"]]
