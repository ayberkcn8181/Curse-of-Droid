"""Run a plan step by step: guard-check everything first, ask before risky steps, wait for device modes."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..transport.adb import Adb
from ..transport.base import Runner, subprocess_runner
from ..transport.fastboot import Fastboot
from .artifacts import ArtifactError, ArtifactRequirement, verify_artifact
from .guard import FileUse, GuardError, base_name, check_command
from .plan import Plan, Step


class UI(Protocol):
    def info(self, text: str) -> None: ...
    def confirm(self, step: Step) -> bool: ...  # risky step: explicit consent
    def manual(self, step: Step) -> bool: ...  # user did something on the phone (False = abort)
    def ask(self, step: Step) -> str: ...  # free-text answer ("" = abort)


@dataclass
class StepFailed(Exception):
    step: Step
    message: str

    def __str__(self):
        return f"{self.step.title}: {self.message}"


def validate(plan: Plan) -> None:
    """Every command of the plan must pass the guard before the first one runs."""
    files = {}
    for step in plan.steps:
        for c in step.commands:
            use = check_command(c.tool, c.args, fastbootd=step.fastbootd, logical_ok=c.logical_ok,
                                allow_unlock=step.unlock, allow_unlock_placeholder=bool(step.ask))
            if plan.target and c.args[:1] in (["-s"], ["-t"]):
                raise GuardError("a bound installation plan cannot override its device selector")
            if use:
                artifact = _required_file(plan, use)
                files[artifact.path] = artifact
    for artifact in files.values():
        verify_artifact(artifact)


def _required_file(plan: Plan, use: FileUse) -> ArtifactRequirement:
    path = Path(use.path)
    matches = [a for a in plan.artifacts if a.path == path]
    if not path.is_absolute() or len(matches) != 1:
        raise ArtifactError("every image/package command needs one captured artifact manifest and an absolute path")
    artifact = matches[0]
    if not plan.target or not plan.target.serial or not plan.target.codenames:
        raise ArtifactError("file operations require an explicit installation target")
    if not {d.lower() for d in plan.target.codenames}.intersection(d.lower() for d in artifact.manifest.devices):
        raise ArtifactError("artifact manifest does not match the bound installation target")
    kind = artifact.manifest.kind
    if (use.operation == "sideload" and kind not in {"rom", "addon"}
            or use.operation == "boot" and kind != "recovery"
            or use.operation == "flash" and kind not in {"gsi", "recovery"}
            or kind == "gsi" and (use.operation != "flash" or base_name(use.partition) != "system")
            or kind == "recovery" and use.operation == "flash" and base_name(use.partition) not in {
                "boot", "init_boot", "vendor_boot", "recovery", "ramdisk", "recovery_ramdisk", "recovery_vendor"}):
        raise ArtifactError("artifact manifest kind does not match the planned operation/partition")
    return artifact


class Executor:
    def __init__(self, adb_exe, fastboot_exe, serial: str | None, ui: UI, runner: Runner = subprocess_runner,
                 sleep: Callable[[float], None] = time.sleep):
        self.adb = Adb(adb_exe, runner, serial)
        self.fastboot = Fastboot(fastboot_exe, runner, serial)
        self.ui, self.sleep = ui, sleep
        self.serial = serial

    def run(self, plan: Plan) -> None:
        try:
            if plan.target and (not self.serial or self.serial != plan.target.serial):
                raise GuardError("executor serial does not match the bound installation target")
            validate(plan)
        except (GuardError, ArtifactError) as e:
            raise StepFailed(plan.steps[0] if plan.steps else Step("plan", ""), f"plan rejected: {e}") from None
        for step in plan.steps:
            self.ui.info(f"→ {step.title}")
            if step.risk in ("data-loss", "system-write") and not self.ui.confirm(step):
                raise StepFailed(step, "cancelled by the user")
            if step.manual and not self.ui.manual(step):
                raise StepFailed(step, "cancelled by the user")
            answer = ""
            if step.ask:
                answer = self.ui.ask(step).strip()
                if not answer or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", answer):
                    raise StepFailed(step, "no valid answer given")
            for c in step.commands:
                args = [x.replace("{answer}", answer) for x in c.args]
                # re-check right before running (defence in depth)
                try:
                    if plan.target and (self.serial != plan.target.serial or args[:1] in (["-s"], ["-t"])):
                        raise GuardError("command no longer matches the bound device selector")
                    use = check_command(c.tool, args, fastbootd=step.fastbootd, logical_ok=c.logical_ok,
                                        allow_unlock=step.unlock)
                    if use:
                        verify_artifact(_required_file(plan, use))
                except (GuardError, ArtifactError) as e:
                    raise StepFailed(step, f"command rejected: {e}") from None
                tool = self.adb if c.tool == "adb" else self.fastboot
                r = tool.run(*args, timeout=c.timeout)
                if step.show_output:
                    self.ui.info((r.stdout + r.stderr).strip())
                # adb sideload exits 0 on success; some recoveries print "Total xfer: 1.00x" and return 1
                if not r.ok and not (c.args[:1] == ["sideload"] and "Total xfer" in r.stdout + r.stderr):
                    raise StepFailed(step, (r.stderr or r.stdout).strip()[-500:] or f"exit {r.returncode}")
            if step.wait_for:
                self.wait_for(step.wait_for, step)

    def current_mode(self) -> str:
        for d in self.adb.devices():
            if self.serial in (None, d.serial):
                return {"device": "android"}.get(d.state, d.state)
        for serial, mode in self.fastboot.devices():
            if self.serial in (None, serial):
                return mode
        return ""

    def wait_for(self, mode: str, step: Step) -> None:
        waited = 0.0
        while waited < step.wait_timeout:
            if self.current_mode() == mode:
                return
            self.sleep(2)
            waited += 2
        raise StepFailed(step, f"the phone didn't show up in {mode} mode within {int(step.wait_timeout)} s")
