"""Fresh installation authorization. Every transport is injected; no phone is used."""
from dataclasses import replace
import subprocess

import pytest

from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash.artifacts import require_artifact
from curseofdroid.flash.device_checks import DeviceGate, execution_blocker
from curseofdroid.flash.executor import Executor, StepFailed, validate
from curseofdroid.flash.guard import GuardError
from curseofdroid.flash.plan import Command, InstallTarget, Plan, Step
from curseofdroid.flash.planner import InstallRequest, plan_gsi_install, preflight
from curseofdroid.transport.adb import Adb
from curseofdroid.transport.base import Result
from curseofdroid.transport.fastboot import Fastboot


TARGET = InstallTarget("S1", ("lavender",), "yes", "a", "yes")


class Phone:
    def __init__(self, mode="fastbootd"):
        self.mode = mode
        self.vars = {"serialno": "S1", "product": "lavender", "unlocked": "yes", "slot-count": "2",
                     "current-slot": "a", "has-slot:system": "yes", "is-logical:system_a": "yes",
                     "partition-size:system_a": "0x100000", "has-slot:userdata": "no",
                     "is-logical:userdata": "no", "partition-size:userdata": "2097152",
                     "max-download-size": "0x100000"}
        self.props = {"ro.serialno": "S1", "ro.boot.serialno": "S1", "ro.product.vendor.device": "lavender",
                      "ro.boot.vbmeta.device_state": "unlocked", "ro.boot.flash.locked": "0",
                      "ro.boot.slot_suffix": "_a", "ro.build.ab_update": "true",
                      "ro.build.version.sdk": "35", "ro.boot.dynamic_partitions": "true"}
        self.calls, self.writes = [], []
        self.adb_override = self.fb_override = self.props_override = None
        self.hook = None

    def __call__(self, argv, timeout):
        argv = list(argv)
        self.calls.append(argv)
        selected = len(argv) > 2 and argv[1] == "-s"
        args = argv[3:] if selected else argv[1:]
        if self.hook:
            result = self.hook(argv, args)
            if result is not None:
                return result
        if argv[0] == "adb" and args == ["devices", "-l"]:
            assert not selected
            state = {"android": "device", "recovery": "recovery", "sideload": "sideload"}.get(self.mode)
            output = f"S1 {state} usb:1\n" if state else ""
            return Result(argv, 0, "List of devices attached\n" + (self.adb_override if self.adb_override is not None else output), "")
        if argv[0] == "fastboot" and args == ["devices"]:
            assert not selected
            # Intentionally label fastbootd as fastboot, matching common tools.
            output = "S1 fastboot\n" if self.mode in {"fastboot", "fastbootd"} else ""
            return Result(argv, 0, self.fb_override if self.fb_override is not None else output, "")
        assert selected and argv[2] == "S1", "all directed probes/writes must select the captured serial"
        if argv[0] == "fastboot" and args[:1] == ["getvar"]:
            value = ("yes" if self.mode == "fastbootd" else "no") if args[1] == "is-userspace" else self.vars.get(args[1])
            if value is None:
                return Result(argv, 1, "", "FAILED (remote: unknown variable)")
            return Result(argv, 0, "", f"(bootloader) {args[1]}: {value}\nFinished. Total time: 0.001s\n")
        if argv[0] == "adb" and args == ["shell", "getprop"]:
            output = "\n".join(f"[{k}]: [{v}]" for k, v in self.props.items())
            return Result(argv, 0, self.props_override if self.props_override is not None else output, "")
        # Anything outside the read-only protocol must be a deliberately expected fake operation.
        assert args[0] in {"flash", "erase", "format", "format:ext4", "reboot", "boot"}, args
        self.writes.append(argv)
        if args[:2] == ["reboot", "fastboot"]:
            self.mode = "fastbootd"
        elif args[0] == "reboot":
            self.mode = "fastboot" if args[1:] == ["bootloader"] else "android"
        elif args[0] == "boot":
            self.mode = "recovery"
        return Result(argv, 0, "", "")


class UI:
    def __init__(self, confirm=None):
        self.change = confirm
        self.manuals, self.confirms = [], []

    def info(self, text): pass
    def confirm(self, step):
        self.confirms.append(step.title)
        return self.change(step) if self.change else True
    def manual(self, step):
        self.manuals.append(step.title)
        return True


def gate(phone, target=TARGET):
    return DeviceGate(Adb("adb", phone, "S1"), Fastboot("fastboot", phone, "S1"), target)


@pytest.fixture
def flash_plan(tmp_path, artifact_manifest):
    path = tmp_path / "system.img"
    path.write_bytes(b"controlled image bytes")
    artifact_manifest(path, "gsi")
    requirement = require_artifact(path, "gsi")
    return Plan("controlled install", [Step("flash", "", "system-write", [
        Command("fastboot", ["flash", "system", str(path)])], fastbootd=True)],
        artifacts=(requirement,), target=TARGET)


def execute(plan, phone, ui=None):
    Executor("adb", "fastboot", "S1", ui or UI(), phone, sleep=lambda _: None).run(plan)


def test_fresh_fastbootd_authorizes_only_the_captured_explicit_slot(flash_plan):
    phone = Phone()
    execute(flash_plan, phone)
    assert phone.writes == [["fastboot", "-s", "S1", "flash", "system_a", str(flash_plan.artifacts[0].path)]]
    assert all(argv[:3] == ["fastboot", "-s", "S1"] for argv in phone.calls if "getvar" in argv)
    assert sum(argv[-2:] == ["getvar", "current-slot"] for argv in phone.calls) == 2
    assert sum(argv[-2:] == ["getvar", "partition-size:system_a"] for argv in phone.calls) == 2


@pytest.mark.parametrize("name,value", [
    ("serialno", "OTHER"), ("product", "oriole"), ("unlocked", "no"), ("unlocked", "unknown"),
    ("slot-count", "1"), ("slot-count", "3"), ("slot-count", "unknown"), ("current-slot", "b"),
    ("current-slot", ""), ("has-slot:system", "unknown"), ("is-logical:system_a", "no"),
    ("partition-size:system_a", "0"), ("partition-size:system_a", "-1"),
    ("partition-size:system_a", "0x0"), ("partition-size:system_a", "1"),
    ("partition-size:system_a", "12 KiB"), ("partition-size:system_a", str(1 << 63)),
    ("partition-size:system_a", "9" * 257),
])
def test_changed_unknown_or_insufficient_fastboot_state_never_writes(flash_plan, name, value):
    phone = Phone()
    phone.vars[name] = value
    with pytest.raises(StepFailed, match="command rejected"):
        execute(flash_plan, phone)
    assert phone.writes == []


@pytest.mark.parametrize("missing", ["serialno", "product", "unlocked", "slot-count", "current-slot",
                                      "has-slot:system", "is-logical:system_a", "partition-size:system_a"])
def test_unsupported_required_variables_stop_instead_of_using_cached_profile(flash_plan, missing):
    phone = Phone()
    del phone.vars[missing]
    with pytest.raises(StepFailed):
        execute(flash_plan, phone)
    assert phone.writes == []


@pytest.mark.parametrize("mode", ["fastboot", "android", "recovery", "sideload", "absent"])
def test_stale_fastbootd_plan_flag_is_not_live_mode_evidence(flash_plan, mode):
    phone = Phone(mode)
    with pytest.raises(StepFailed):
        execute(flash_plan, phone)
    assert phone.writes == []


@pytest.mark.parametrize("adb,fb", [
    ("S1 device\n", "S1 fastboot\n"), ("", "S1 fastboot\nS1 fastboot\n"),
    ("S1 device\nS1 device\n", ""), ("S1 offline\n", ""),
    ("S1 unauthorized\n", ""), ("", "S1 strange\n"), ("OTHER fastboot\n", ""),
])
def test_inventory_duplicates_unauthorized_and_other_devices_fail_closed(flash_plan, adb, fb):
    phone = Phone()
    phone.adb_override, phone.fb_override = adb, fb
    with pytest.raises(StepFailed):
        execute(flash_plan, phone)
    assert phone.writes == []


@pytest.mark.parametrize("failure", ["exit", "error", "failed", "duplicate", "large", "oserror", "timeout"])
def test_failed_or_ambiguous_probes_are_not_empty_device_lists(flash_plan, failure):
    phone = Phone()
    def fail(argv, args):
        if args != ["getvar", "unlocked"]:
            return
        if failure == "oserror": raise OSError("private USB diagnostic")
        if failure == "timeout": raise subprocess.TimeoutExpired(argv, 10)
        data = {"exit": (1, "unlocked: yes"), "error": (0, "unlocked: yes\nerror: private diagnostic"),
                "failed": (0, "unlocked: yes\n(bootloader) FAILED private diagnostic"),
                "duplicate": (0, "unlocked: yes\nunlocked: no"), "large": (0, "x" * ((1 << 20) + 1))}
        code, output = data[failure]
        return Result(argv, code, "", output)
    phone.hook = fail
    with pytest.raises(StepFailed) as error:
        execute(flash_plan, phone)
    assert "private" not in str(error.value) and phone.writes == []


@pytest.mark.parametrize("change", ["unlocked", "slot", "capacity", "logical", "mode", "file", "selector"])
def test_changes_while_probing_stop_before_the_file_is_opened_by_fastboot(flash_plan, change):
    phone = Phone()
    def mutate(argv, args):
        if args == ["getvar", "partition-size:system_a"]:
            phone.hook = None
            if change == "unlocked": phone.vars["unlocked"] = "no"
            elif change == "slot": phone.vars["current-slot"] = "b"
            elif change == "mode": phone.mode = "fastboot"
            elif change == "file": flash_plan.artifacts[0].path.write_bytes(b"x" * flash_plan.artifacts[0].manifest.size)
            elif change == "selector": executor.fastboot.serial = "OTHER"
            else:
                value = phone.vars["partition-size:system_a"]
                phone.vars["partition-size:system_a" if change == "capacity" else "is-logical:system_a"] = "2097152" if change == "capacity" else "no"
                return Result(argv, 0, "", f"partition-size:system_a: {value}")
    phone.hook = mutate
    executor = Executor("adb", "fastboot", "S1", UI(), phone)
    # If selector changes, no further directed probe may run on OTHER either.
    with pytest.raises(StepFailed):
        executor.run(flash_plan)
    assert phone.writes == []


def test_each_write_rechecks_unlock_state_instead_of_reusing_authorization(flash_plan):
    phone = Phone()
    flash_plan.steps.append(Step("second write", "", "system-write", [
        Command("fastboot", ["flash", "system", str(flash_plan.artifacts[0].path)])], fastbootd=True))
    def lock_after_write(argv, args):
        if args[0] == "flash":
            phone.vars["unlocked"] = "no"
    phone.hook = lock_after_write
    with pytest.raises(StepFailed, match="unlocked"):
        execute(flash_plan, phone)
    assert len(phone.writes) == 1


def test_confirmation_cannot_authorize_a_changed_target_or_risk(flash_plan):
    for change in ("target", "risk"):
        phone = Phone()
        original = flash_plan.target
        def mutate(step):
            if change == "target": flash_plan.target = replace(original, current_slot="b")
            else: step.risk = "data-loss"
            return True
        with pytest.raises(StepFailed, match="target changed|consent risk"):
            execute(flash_plan, phone, UI(mutate))
        assert phone.calls == []
        flash_plan.target, flash_plan.steps[0].risk = original, "system-write"


def test_sparse_expanded_size_is_checked_not_tiny_file_size(flash_plan, artifact_manifest):
    from test_image_size import chunk, header
    path = flash_plan.artifacts[0].path
    path.write_bytes(header(blocks=1024) + chunk(blocks=1024))
    artifact_manifest(path, "gsi")
    flash_plan.artifacts = (require_artifact(path, "gsi"),)
    phone = Phone()
    with pytest.raises(StepFailed, match="expanded image exceeds"):
        execute(flash_plan, phone)
    assert path.stat().st_size == 40 and phone.writes == []


def test_legacy_physical_system_and_explicit_a_only_layout(flash_plan):
    phone = Phone("fastboot")
    flash_plan.target = replace(TARGET, ab="no", current_slot="", dynamic_partitions="no")
    flash_plan.steps[0].fastbootd = False
    flash_plan.steps[0].commands[0].logical_ok = True
    phone.vars.update({"slot-count": "1", "has-slot:system": "no", "is-logical:system": "no",
                       "partition-size:system": "1048576"})
    execute(flash_plan, phone)
    assert phone.writes[0][3:5] == ["flash", "system"]


@pytest.mark.parametrize("partition", ["system_b", "system_a"])
def test_explicit_wrong_or_unsupported_slot_is_rejected(flash_plan, partition):
    phone = Phone()
    flash_plan.steps[0].commands[0].args[1] = partition
    if partition == "system_a": phone.vars["has-slot:system"] = "no"
    with pytest.raises(StepFailed, match="slot"):
        execute(flash_plan, phone)
    assert phone.writes == []


def test_bound_wipe_requires_matching_consent_and_current_identity():
    phone = Phone()
    plan = Plan("wipe", [Step("wipe", "", "data-loss", [Command("fastboot", ["erase", "userdata"])])], target=TARGET)
    execute(plan, phone)
    assert phone.writes == [["fastboot", "-s", "S1", "erase", "userdata"]]
    plan.steps[0].risk = "none"
    with pytest.raises(GuardError, match="matching consent risk"): validate(plan)
    plan.steps[0].risk, plan.target = "data-loss", None
    with pytest.raises(GuardError, match="bound target"): validate(plan)


@pytest.mark.parametrize("args", [["-w"], ["--slot=all", "reboot"], ["set_active", "b"], ["continue"]])
def test_implicit_multi_partition_wipes_and_slot_overrides_are_blocked_before_probes(args):
    phone = Phone()
    plan = Plan("blocked", [Step("operation", "", "data-loss", [Command("fastboot", args)])], target=TARGET)
    with pytest.raises(StepFailed, match="plan rejected"):
        execute(plan, phone)
    assert phone.calls == []


def test_command_mutated_to_aggregate_wipe_after_consent_is_blocked(flash_plan):
    phone = Phone()
    def mutate(step):
        step.commands[0].args = ["-w"]
        step.risk = "data-loss"
        return True
    with pytest.raises(StepFailed, match="Aggregate fastboot"):
        execute(flash_plan, phone, UI(mutate))
    assert phone.calls == []


@pytest.mark.parametrize("change", ["serial", "product", "locked", "conflict", "ab", "slot", "dynamic", "duplicate"])
def test_adb_identity_is_fresh_before_any_reboot(change):
    phone = Phone("android")
    if change == "serial": phone.props["ro.boot.serialno"] = "OTHER"
    elif change == "product": phone.props["ro.product.vendor.device"] = "oriole"
    elif change == "locked": phone.props["ro.boot.vbmeta.device_state"] = "locked"
    elif change == "conflict": phone.props["ro.boot.flash.locked"] = "1"
    elif change == "ab": del phone.props["ro.boot.slot_suffix"]
    elif change == "slot": phone.props["ro.boot.slot_suffix"] = "_b"
    elif change == "dynamic": phone.props["ro.boot.dynamic_partitions"] = "false"
    else: phone.props_override = "[ro.serialno]: [S1]\n[ro.serialno]: [S1]"
    plan = Plan("reboot", [Step("reboot", "", commands=[Command("adb", ["reboot", "bootloader"])])], target=TARGET)
    with pytest.raises(StepFailed): execute(plan, phone)
    assert phone.writes == []


def test_mode_transition_rechecks_real_fastbootd_before_gsi_write(flash_plan):
    phone = Phone("android")
    profile = DeviceProfile(serial="S1", codenames=["lavender"], mode="android", bootloader_unlocked="yes",
                            treble="yes", abi="arm64-v8a", ab="yes", current_slot="a", dynamic_partitions="yes")
    plan = plan_gsi_install(profile, flash_plan.artifacts[0].path, wipe_data=False)
    execute(plan, phone)
    assert [argv[3:5] for argv in phone.writes] == [["reboot", "bootloader"], ["reboot", "fastboot"],
                                                  ["flash", "system_a"], ["reboot"]]
    assert phone.mode == "android"


def test_manual_wipe_does_not_display_instructions_for_a_changed_device():
    phone = Phone("recovery")
    phone.props["ro.boot.serialno"] = "OTHER"
    ui = UI()
    plan = Plan("manual", [Step("format data", "", "data-loss", manual="format data in recovery")], target=TARGET)
    with pytest.raises(StepFailed, match="manual step rejected"): execute(plan, phone, ui)
    assert ui.manuals == [] and phone.writes == []


def test_mode_wait_failure_is_not_polled_as_device_absence():
    phone = Phone()
    executor = Executor("adb", "fastboot", "S1", UI(), phone, sleep=lambda _: pytest.fail("must stop immediately"))
    executor._device_gate = gate(phone)
    def fail(argv, args):
        if args == ["devices", "-l"]: return Result(argv, 1, "", "private failure")
    phone.hook = fail
    with pytest.raises(StepFailed, match="mode check failed"):
        executor.wait_for("android", Step("wait", ""))


def test_capture_copies_layout_and_unknown_ab_blocks_execution():
    profile = DeviceProfile(serial="S1", codenames=["lavender"], ab="yes", current_slot="a", dynamic_partitions="yes")
    captured = InstallTarget.from_profile(profile)
    profile.current_slot = "b"
    profile.codenames.append("other")
    assert captured == TARGET
    plan = Plan("unknown", [], target=replace(TARGET, ab="unknown"))
    assert "captured A/B" in execution_blocker(plan)


@pytest.mark.parametrize("change", ["locked", "slot", "product"])
def test_changed_device_during_consent_is_checked_after_user_returns(flash_plan, change):
    phone = Phone()
    def mutate(step):
        phone.vars[{"locked": "unlocked", "slot": "current-slot", "product": "product"}[change]] = {
            "locked": "no", "slot": "b", "product": "oriole"}[change]
        return True
    with pytest.raises(StepFailed): execute(flash_plan, phone, UI(mutate))
    assert phone.writes == []


@pytest.mark.parametrize("kind", ["raw", "large", "sparse", "userspace", "missing-limit"])
def test_temporary_boot_checks_mode_raw_extent_and_download_limit(tmp_path, artifact_manifest, kind):
    from test_image_size import chunk, header
    path = tmp_path / "recovery.img"
    path.write_bytes(header() + chunk() if kind == "sparse" else b"controlled boot image")
    artifact_manifest(path, "recovery")
    plan = Plan("boot", [Step("boot once", "", "reboot", [Command("fastboot", ["boot", str(path)])])],
                artifacts=(require_artifact(path, "recovery"),), target=TARGET)
    phone = Phone("fastbootd" if kind == "userspace" else "fastboot")
    if kind == "large": phone.vars["max-download-size"] = "1"
    if kind == "missing-limit": del phone.vars["max-download-size"]
    if kind == "raw":
        execute(plan, phone)
        assert phone.writes == [["fastboot", "-s", "S1", "boot", str(path)]]
    else:
        with pytest.raises(StepFailed): execute(plan, phone)
        assert phone.writes == []


def test_small_valid_sparse_image_uses_expanded_capacity(flash_plan, artifact_manifest):
    from test_image_size import chunk, header
    path = flash_plan.artifacts[0].path
    path.write_bytes(header() + chunk())
    artifact_manifest(path, "gsi")
    flash_plan.artifacts = (require_artifact(path, "gsi"),)
    phone = Phone()
    phone.vars["partition-size:system_a"] = "4096"
    execute(flash_plan, phone)
    assert len(phone.writes) == 1


def test_explicit_a_only_adb_properties_can_reboot_but_sdk_alone_cannot():
    target = replace(TARGET, ab="no", current_slot="", dynamic_partitions="no")
    for explicit in (True, False):
        phone = Phone("android")
        phone.props.pop("ro.boot.slot_suffix")
        phone.props["ro.boot.dynamic_partitions"] = "false"
        if explicit: phone.props["ro.build.ab_update"] = "false"
        else: phone.props.pop("ro.build.ab_update")
        plan = Plan("reboot", [Step("reboot", "", commands=[Command("adb", ["reboot", "bootloader"])])], target=target)
        if explicit:
            execute(plan, phone)
            assert len(phone.writes) == 1
        else:
            with pytest.raises(StepFailed, match="not explicitly confirmed"): execute(plan, phone)
            assert phone.writes == []


def test_manual_instruction_checks_device_after_consent_returns():
    phone = Phone("recovery")
    def change(step):
        phone.props["ro.boot.serialno"] = "OTHER"
        return True
    ui = UI(change)
    plan = Plan("manual", [Step("format data", "", "data-loss", manual="format data in recovery")], target=TARGET)
    with pytest.raises(StepFailed, match="manual step rejected"): execute(plan, phone, ui)
    assert ui.manuals == []


def test_unknown_rom_slot_layout_is_rejected_by_planning():
    from types import SimpleNamespace
    profile = DeviceProfile(serial="S1", codenames=["lavender"], bootloader_unlocked="yes")
    request = InstallRequest(SimpleNamespace(kind="ota-zip", matches=lambda _: True))
    assert any("A/B layout" in item for item in preflight(profile, request))


@pytest.mark.parametrize("args", [["erase", "userdata"], ["format:f2fs", "cache"], ["-w"],
                                  ["--slot=all", "erase", "userdata"],
                                  ["-s", "S1", "--skip-reboot", "format:ext4", "metadata"]])
def test_wipe_risk_cannot_be_hidden_behind_selectors_or_options(args):
    plan = Plan("unbound wipe", [Step("bad risk", "", commands=[Command("fastboot", args)])])
    with pytest.raises(GuardError, match="bound target and matching consent risk"):
        validate(plan)


def test_malformed_full_property_set_stops_as_a_preflight_error():
    phone = Phone("android")
    phone.props["ro.build.version.sdk"] = "9" * 5000
    plan = Plan("reboot", [Step("reboot", "", commands=[Command("adb", ["reboot", "bootloader"])])], target=TARGET)
    with pytest.raises(StepFailed, match="malformed"): execute(plan, phone)
    assert phone.writes == []
