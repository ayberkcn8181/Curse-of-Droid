"""Read-only command errors must not masquerade as successful empty discovery."""
from pathlib import Path

import pytest

from curseofdroid.device.detect import detect
from curseofdroid.transport.adb import Adb
from curseofdroid.transport.base import Result, TransportError
from curseofdroid.transport.fastboot import Fastboot


@pytest.mark.parametrize("factory,method,args", [
    (Adb, "devices", ()), (Adb, "getprop", ()), (Adb, "shell", ("getprop",)),
    (Fastboot, "devices", ()), (Fastboot, "getvar_all", ()), (Fastboot, "getvar", ("product",)),
])
def test_read_failures_are_explicit_and_redact_identifiers(factory, method, args):
    commands = []

    def runner(argv, timeout):
        commands.append(list(argv))
        return Result(list(argv), 1, "PRIVATE-SERIAL", "permission denied for PRIVATE-SERIAL")

    tool = factory("tool", runner, serial="PRIVATE-SERIAL")
    with pytest.raises(TransportError, match="failed.*exit 1") as failure:
        getattr(tool, method)(*args)
    assert failure.value.returncode == 1
    assert "PRIVATE-SERIAL" not in str(failure.value)
    assert commands[0][:3] == ["tool", "-s", "PRIVATE-SERIAL"]


@pytest.mark.parametrize("transport", ["adb", "fastboot"])
def test_detection_does_not_report_disconnected_on_listing_failure(transport):
    def runner(argv, timeout):
        rc = 1 if argv[0] == transport else 0
        return Result(list(argv), rc, "", "connection failed" if rc else "")

    with pytest.raises(TransportError):
        detect("adb", "fastboot", runner)


def test_optional_battery_failure_keeps_known_device_profile():
    props = Path("tests/fixtures/huawei_atu_l21_lineage17_getprop.txt").read_text()

    def runner(argv, timeout):
        if argv == ["adb", "devices", "-l"]:
            return Result(list(argv), 0, "SERIAL device\n", "")
        if argv[-2:] == ["shell", "getprop"]:
            return Result(list(argv), 0, props, "")
        if "shell" in argv:
            return Result(list(argv), 1, "", "battery probe unsupported")
        return Result(list(argv), 0, "", "")

    devices = detect("adb", "fastboot", runner)
    assert len(devices) == 1
    assert devices[0].profile.codename == "msm8937_64"
    assert devices[0].profile.battery_percent is None


def test_successful_empty_discovery_remains_empty():
    def runner(argv, timeout):
        return Result(list(argv), 0, "", "")

    assert detect("adb", "fastboot", runner) == []


@pytest.mark.parametrize("command_exit,cli_exit", [(0, 1), (1, 2)])
def test_cli_distinguishes_no_phone_from_command_error(command_exit, cli_exit, monkeypatch, capsys):
    from curseofdroid import cli
    from curseofdroid.platform.tools import Tools

    def runner(argv, timeout):
        return Result(list(argv), command_exit, "", "PRIVATE-SERIAL")

    monkeypatch.setattr(cli, "find_tools", lambda: Tools(Path("adb"), Path("fastboot"), "PATH"))
    monkeypatch.setattr(cli, "detect", lambda a, f: detect(a, f, runner))
    assert cli.main(["detect"]) == cli_exit
    out = capsys.readouterr()
    if command_exit:
        assert "No phone found" not in out.out
        assert "failed (exit 1)" in out.err
        assert "PRIVATE-SERIAL" not in out.err
    else:
        assert "No phone found" in out.out and not out.err
