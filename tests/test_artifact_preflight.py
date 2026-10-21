"""Real local bytes + injected transports; no device operation is executed."""

import json
import os
import zipfile
from dataclasses import replace
from types import SimpleNamespace

import pytest

from curseofdroid import cli
from curseofdroid.device.detect import Detected
from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash.artifacts import ArtifactError, MAX_MANIFEST, manifest_path, require_artifact, verify_artifact
from curseofdroid.flash.executor import Executor, StepFailed, validate
from curseofdroid.flash.package import inspect
from curseofdroid.flash.plan import Command, InstallTarget, Plan, Step
from curseofdroid.flash.planner import InstallRequest, PlanError, plan_gsi_install, plan_sideload_install
from curseofdroid.transport.base import Result


@pytest.fixture
def device():
    return DeviceProfile(serial="S1", mode="android", codenames=["lavender"], bootloader_unlocked="yes",
                         battery_percent=80, treble="yes", abi="arm64-v8a", dynamic_partitions="yes",
                         ab="yes", current_slot="a", system_as_root="yes")


@pytest.fixture
def image(tmp_path, artifact_manifest):
    path = tmp_path / "system.img"
    path.write_bytes(b"controlled image bytes")
    artifact_manifest(path, "gsi")
    return path


@pytest.fixture
def rom(tmp_path, artifact_manifest):
    path = tmp_path / "ROM.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.bin", b"controlled payload")
        archive.writestr("META-INF/com/android/metadata", "pre-device=lavender\n")
    artifact_manifest(path)
    return path


@pytest.mark.parametrize("changes", [
    {"version": 2}, {"version": True}, {"filename": "other.zip"}, {"kind": "recovery"},
    {"size": 0}, {"size": -1}, {"size": True}, {"size": "20"}, {"size": 2**63},
    {"sha256": "0" * 32}, {"sha256": "g" * 64}, {"sha256": None},
    {"source_url": "http://publisher.example/checksum"}, {"source_url": "https:///missing-host"},
    {"source_url": "https://user:secret@publisher.example/checksum"},
    {"source_url": "https://@publisher.example/checksum"},
    {"source_url": "https://publisher.example/#checksum"}, {"source_url": "https://publisher.example:bad/"},
    {"source_url": "https://publisher.example/\nchecksum"}, {"source_url": None},
    {"devices": []}, {"devices": "lavender"}, {"devices": ["lavender", "LAVENDER"]},
    {"devices": ["../lavender"]}, {"devices": [None]}, {"devices": ["x"] * 33},
    {"abi": "arm64-v8a"}, {"layout": "system-as-root"}, {"verified": True},
])
def test_invalid_or_saved_verified_metadata_cannot_authorize_a_file(rom, artifact_manifest, changes):
    artifact_manifest(rom, **changes)
    with pytest.raises(ArtifactError):
        require_artifact(rom, "rom")


@pytest.mark.parametrize("raw", [b"[]", b"{}", b"\xff", b'{"version":1,"version":1}',
                                  b" " * (MAX_MANIFEST + 1), b"[" * 2000],
                         ids=["array", "missing-fields", "invalid-utf8", "duplicate-fields", "oversize", "deep-nesting"])
def test_invalid_duplicate_or_unbounded_manifest_input_is_refused(rom, raw):
    manifest_path(rom).write_bytes(raw)
    with pytest.raises(ArtifactError):
        require_artifact(rom, "rom")


def test_missing_reference_and_missing_file_are_refused(rom):
    manifest_path(rom).unlink()
    with pytest.raises(ArtifactError, match="manifest.json"):
        require_artifact(rom, "rom")
    rom.unlink()
    with pytest.raises(ArtifactError):
        require_artifact(rom, "rom")


def test_same_size_wrong_bytes_fail_a_real_sha256_check(rom):
    expected = rom.read_bytes()
    rom.write_bytes(bytes(b ^ 1 for b in expected))
    requirement = require_artifact(rom, "rom")  # captures current identity, old expected SHA-256
    with pytest.raises(ArtifactError, match="SHA-256"):
        verify_artifact(requirement)


def test_replacing_sidecar_cannot_replace_an_in_memory_reference(rom, artifact_manifest):
    requirement = require_artifact(rom, "rom")
    original = requirement.manifest.sha256
    artifact_manifest(rom, sha256="0" * 64)
    verify_artifact(requirement)
    assert requirement.manifest.sha256 == original
    with pytest.raises(ArtifactError, match="SHA-256"):
        verify_artifact(require_artifact(rom, "rom"))


def test_same_size_edit_with_restored_mtime_is_not_a_validated_file(rom):
    requirement = require_artifact(rom, "rom")
    info = rom.stat()
    rom.write_bytes(b"x" * info.st_size)
    os.utime(rom, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(ArtifactError):
        verify_artifact(requirement)


def test_symlink_does_not_inherit_a_valid_manifest(rom):
    content = rom.read_bytes()
    other = rom.with_name("other.zip")
    other.write_bytes(content)
    rom.unlink()
    try:
        rom.symlink_to(other)
    except OSError:
        pytest.skip("OS account cannot create symlinks")
    with pytest.raises(ArtifactError, match="regular files"):
        require_artifact(rom, "rom")


def test_manifest_and_directory_must_be_regular_files(rom):
    manifest_path(rom).unlink()
    manifest_path(rom).mkdir()
    with pytest.raises(ArtifactError, match="regular files"):
        require_artifact(rom, "rom")


def test_replacement_between_stat_and_open_is_refused(rom, monkeypatch):
    from curseofdroid.flash import artifacts

    requirement = require_artifact(rom, "rom")
    original_open = artifacts._open_regular

    def replace_before_open(path):
        replacement = path.with_name("replacement.zip")
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
        return original_open(path)

    monkeypatch.setattr(artifacts, "_open_regular", replace_before_open)
    with pytest.raises(ArtifactError, match="changed before verification"):
        verify_artifact(requirement)


def test_different_path_and_handle_ctime_semantics_do_not_disable_identity_checks(rom, monkeypatch):
    from curseofdroid.flash import artifacts

    original_regular = artifacts._regular

    def path_stat(path):
        s = original_regular(path)
        return SimpleNamespace(st_dev=s.st_dev, st_ino=s.st_ino, st_size=s.st_size,
                               st_mtime_ns=s.st_mtime_ns, st_ctime_ns=s.st_ctime_ns - 1_000_000)

    monkeypatch.setattr(artifacts, "_regular", path_stat)
    requirement = require_artifact(rom, "rom")
    verify_artifact(requirement)
    # A changed handle identity is still refused even when path metadata matches.
    altered = replace(requirement, identity=requirement.identity[:-1] + (requirement.identity[-1] - 1,))
    with pytest.raises(ArtifactError, match="changed before verification"):
        verify_artifact(altered)


def test_file_changes_during_streaming_are_refused(rom, monkeypatch):
    from curseofdroid.flash import artifacts

    requirement = require_artifact(rom, "rom")
    original_open = artifacts._open_regular

    class MutatingReader:
        def __enter__(self):
            self.stream = original_open(rom)
            self.changed = False
            return self

        def __exit__(self, *args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            data = self.stream.read(size)
            if data and not self.changed:
                self.changed = True
                rom.write_bytes(b"x" * rom.stat().st_size)
            return data

    monkeypatch.setattr(artifacts, "_open_regular", lambda _: MutatingReader())
    with pytest.raises(ArtifactError):
        verify_artifact(requirement)


@pytest.mark.parametrize("change", [
    {"bootloader_unlocked": "unknown"}, {"bootloader_unlocked": "no"}, {"serial": ""}, {"codenames": []},
    {"treble": "unknown"}, {"treble": "no"}, {"abi": ""}, {"abi": "armeabi-v7a"},
    {"dynamic_partitions": "unknown"}, {"ab": "unknown"}, {"current_slot": ""},
    {"ab": "no", "system_as_root": "unknown"}, {"ab": "no", "system_as_root": "no"},
    {"mode": "fastbootd", "dynamic_partitions": "no"}, {"battery_percent": 20},
])
def test_gsi_plan_refuses_unknown_or_incompatible_device_state(device, image, change):
    with pytest.raises(PlanError):
        plan_gsi_install(replace(device, **change), image)


@pytest.mark.parametrize("change", [
    {"devices": ["oriole"]}, {"abi": "armeabi-v7a"}, {"layout": "legacy"},
    {"kind": "rom"}, {"size": 1}, {"abi": ""}, {"layout": ""},
])
def test_gsi_reference_must_match_artifact_role_device_and_layout(device, image, artifact_manifest, change):
    artifact_manifest(image, **{"kind": "gsi", **change})
    with pytest.raises(PlanError):
        plan_gsi_install(device, image)


@pytest.mark.parametrize("change", [{"bootloader_unlocked": "unknown"}, {"serial": ""}, {"codenames": []}])
def test_rom_plan_requires_a_known_unlocked_target(device, rom, change):
    with pytest.raises(PlanError):
        plan_sideload_install(replace(device, **change), InstallRequest(inspect(rom)))


def test_valid_rom_and_gsi_plans_bind_absolute_paths_and_references(device, rom, image, monkeypatch, tmp_path):
    rom_plan = plan_sideload_install(device, InstallRequest(inspect(rom)))
    gsi_plan = plan_gsi_install(device, image)
    monkeypatch.chdir(tmp_path.parent)
    for plan in (rom_plan, gsi_plan):
        validate(plan)
        assert plan.target.serial == "S1" and plan.target.codenames == ("lavender",)
        assert all(a.path.is_absolute() for a in plan.artifacts)
        assert "Required file checks" in plan.render()
        assert "SHA-256" in plan.render()


def test_recovery_and_every_addon_need_their_own_matching_manifest(device, rom, image, artifact_manifest):
    recovery = image.with_name("recovery.img")
    recovery.write_bytes(b"controlled recovery")
    request = InstallRequest(inspect(rom), recovery=recovery)
    with pytest.raises(PlanError, match="manifest.json"):
        plan_sideload_install(device, request)
    artifact_manifest(recovery, "recovery")
    addon = rom.with_name("addon.zip")
    addon.write_bytes(rom.read_bytes())
    request.extras = (inspect(addon),)
    with pytest.raises(PlanError, match="manifest.json"):
        plan_sideload_install(device, request)
    artifact_manifest(addon, "addon")
    plan = plan_sideload_install(device, request)
    validate(plan)
    assert {a.manifest.kind for a in plan.artifacts} == {"rom", "recovery", "addon"}


@pytest.mark.parametrize("partition", ["recovery", "boot", "vendor_boot"])
def test_supported_recovery_flash_plans_keep_their_file_binding(device, rom, image, artifact_manifest, partition):
    artifact_manifest(image, "recovery")
    plan = plan_sideload_install(device, InstallRequest(inspect(rom), recovery=image,
                                                       flash_recovery=True, recovery_partition=partition))
    validate(plan)
    assert any(c.args[:2] == ["flash", partition] for s in plan.steps for c in s.commands)


class UI:
    def info(self, text): pass
    def confirm(self, step): return True
    def manual(self, step): return True


def file_plan(path, kind="rom"):
    requirement = require_artifact(path, kind)
    return Plan("controlled test", [Step("file", "", "system-write", [Command("adb", ["sideload", str(path)])])],
                artifacts=(requirement,), target=InstallTarget("S1", ("lavender",), "yes", "a", "yes"))


def runner_log():
    calls = []

    def runner(args, timeout):
        calls.append(list(args))
        return Result(list(args), 0, "", "")
    return calls, runner


def test_invalid_late_hash_stops_even_an_earlier_reboot(rom):
    rom.write_bytes(b"x" * rom.stat().st_size)
    plan = file_plan(rom)
    plan.steps.insert(0, Step("earlier reboot", "", commands=[Command("adb", ["reboot", "recovery"])]))
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="plan rejected.*SHA-256"):
        Executor("adb", "fastboot", "S1", UI(), runner).run(plan)
    assert calls == []


def test_file_edit_during_confirmation_stops_before_transport(rom, artifact_manifest):
    artifact_manifest(rom, "recovery")
    plan = file_plan(rom, "recovery")
    plan.steps[0].commands[0] = Command("fastboot", ["boot", str(rom)])
    calls, runner = runner_log()

    class ChangingUI(UI):
        def confirm(self, step):
            rom.write_bytes(b"x" * rom.stat().st_size)
            return True

    with pytest.raises(StepFailed, match="command rejected"):
        Executor("adb", "fastboot", "S1", ChangingUI(), runner).run(plan)
    assert calls == []


@pytest.mark.parametrize("serial", [None, "OTHER"])
def test_a_plan_cannot_be_sent_to_an_implicitly_selected_or_different_device(rom, serial):
    plan = file_plan(rom)
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="serial does not match"):
        Executor("adb", "fastboot", serial, UI(), runner).run(plan)
    assert calls == []


@pytest.mark.parametrize("selector", [["-s", "OTHER"], ["-t", "1"]])
def test_bound_plans_reject_per_command_device_overrides(rom, selector):
    plan = file_plan(rom)
    plan.steps[0].commands[0].args[:0] = selector
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="device selector"):
        Executor("adb", "fastboot", "S1", UI(), runner).run(plan)
    assert calls == []


def test_selector_added_during_confirmation_is_also_rejected(rom, artifact_manifest):
    artifact_manifest(rom, "recovery")
    plan = file_plan(rom, "recovery")
    plan.steps[0].commands[0] = Command("fastboot", ["boot", str(rom)])
    calls, runner = runner_log()

    class ChangingUI(UI):
        def confirm(self, step):
            step.commands[0].args[:0] = ["-s", "OTHER"]
            return True

    with pytest.raises(StepFailed, match="command rejected.*device selector"):
        Executor("adb", "fastboot", "S1", ChangingUI(), runner).run(plan)
    assert calls == []


@pytest.mark.parametrize("args", [None, "reboot", [None]])
def test_malformed_bound_command_fails_as_a_plan_error_before_any_runner(rom, args):
    plan = file_plan(rom)
    plan.steps[0].commands[0].args = args
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="plan rejected"):
        Executor("adb", "fastboot", "S1", UI(), runner).run(plan)
    assert calls == []


@pytest.mark.parametrize("change", ["no-reference", "duplicate-reference", "relative-path", "wrong-target"])
def test_unbound_ambiguous_or_mismatched_file_uses_are_rejected(rom, change):
    plan = file_plan(rom)
    if change == "no-reference":
        plan.artifacts = ()
    elif change == "duplicate-reference":
        plan.artifacts *= 2
    elif change == "relative-path":
        plan.steps[0].commands[0].args[-1] = rom.name
    else:
        plan.target = InstallTarget("S1", ("oriole",))
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="plan rejected"):
        Executor("adb", "fastboot", "S1", UI(), runner).run(plan)
    assert calls == []


@pytest.mark.parametrize("kind,args", [
    ("gsi", ["boot"]), ("gsi", ["flash", "boot"]), ("recovery", ["sideload"]),
    ("recovery", ["flash", "super"]), ("rom", ["boot"]),
])
def test_manifest_roles_cannot_be_reused_for_a_different_operation(rom, artifact_manifest, kind, args):
    artifact_manifest(rom, kind)
    plan = file_plan(rom, kind)
    plan.steps[0].commands[0] = Command("adb" if args[0] == "sideload" else "fastboot", args + [str(rom)])
    with pytest.raises(ArtifactError, match="kind does not match"):
        validate(plan)


def test_sideload_is_blocked_before_reboot_or_manual_wipe(rom):
    plan = file_plan(rom)
    plan.steps.insert(0, Step("reboot", "", commands=[Command("adb", ["reboot", "recovery"])]))
    calls, runner = runner_log()
    with pytest.raises(StepFailed, match="Automatic sideload is blocked"):
        Executor("adb", "fastboot", "S1", UI(), runner).run(plan)
    assert calls == []


def setup_cli(monkeypatch, device):
    monkeypatch.setattr(cli, "_need_tools", lambda: SimpleNamespace(adb="adb", fastboot="fastboot"))
    monkeypatch.setattr(cli, "_one_device", lambda _: Detected("S1", "android", device))
    monkeypatch.setattr("builtins.input", lambda _: pytest.fail("unexpected execution/consent prompt"))
    monkeypatch.setattr(cli.Executor, "run", lambda *_: pytest.fail("unexpected executor call"))


def test_cli_rom_dry_run_performs_full_hash_verification(device, rom, monkeypatch, capsys):
    setup_cli(monkeypatch, device)
    args = SimpleNamespace(rom=str(rom), recovery=None, recovery_name="", flash_recovery=False,
                           recovery_partition="recovery", keep_data=False, extra=[], dry_run=True)
    assert cli.cmd_install(args) == 0
    assert "dry run: nothing was done" in capsys.readouterr().out
    reference = json.loads(manifest_path(rom).read_text())
    reference["sha256"] = "0" * 64
    manifest_path(rom).write_text(json.dumps(reference))
    assert cli.cmd_install(args) == 1
    assert "SHA-256" in capsys.readouterr().out


def test_cli_gsi_dry_run_and_xz_refusal_are_read_only(device, image, monkeypatch, capsys):
    setup_cli(monkeypatch, device)
    args = SimpleNamespace(install=str(image), keep_data=False, dry_run=True)
    assert cli.cmd_gsi(args) == 0
    assert "dry run: nothing was done" in capsys.readouterr().out
    args.install = str(image) + ".xz"
    monkeypatch.setattr(cli, "unpack_xz", lambda *_: pytest.fail("unvalidated automatic extraction"))
    assert cli.cmd_gsi(args) == 1
    assert "unpack the image first" in capsys.readouterr().out


def test_cli_blocked_sideload_returns_before_start_or_wipe_prompt(device, rom, monkeypatch, capsys):
    setup_cli(monkeypatch, device)
    args = SimpleNamespace(rom=str(rom), recovery=None, recovery_name="", flash_recovery=False,
                           recovery_partition="recovery", keep_data=False, extra=[], dry_run=False)
    assert cli.cmd_install(args) == 1
    assert "Automatic sideload is blocked" in capsys.readouterr().out


def test_cli_aggregate_gsi_wipe_is_visible_in_dry_run_and_blocked_before_start(device, image, monkeypatch, capsys):
    setup_cli(monkeypatch, device)
    args = SimpleNamespace(install=str(image), keep_data=False, dry_run=True)
    assert cli.cmd_gsi(args) == 0
    assert "Aggregate fastboot -w is blocked" in capsys.readouterr().out
    args.dry_run = False
    assert cli.cmd_gsi(args) == 1
