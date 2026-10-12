"""Run a plan step by step: guard-check everything first, ask before risky steps, wait for device modes."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from ..transport.adb import Adb
from ..transport.base import Runner, subprocess_runner
from ..transport.fastboot import Fastboot
from .guard import GuardError, check_command
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
    for step in plan.steps:
        for c in step.commands:
            check_command(c.tool, c.args, fastbootd=step.fastbootd, logical_ok=c.logical_ok,
                          allow_unlock=step.unlock)


class Executor:
    def __init__(self, adb_exe, fastboot_exe, serial: str | None, ui: UI, runner: Runner = subprocess_runner,
                 sleep: Callable[[float], None] = time.sleep):
        self.adb = Adb(adb_exe, runner, serial)
        self.fastboot = Fastboot(fastboot_exe, runner, serial)
        self.ui, self.sleep = ui, sleep
        self.serial = serial

    def run(self, plan: Plan) -> None:
        try:
            validate(plan)
        except GuardError as e:
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
                if not answer or not re.fullmatch(r"[\w-]{1,128}", answer):
                    raise StepFailed(step, "no valid answer given")
            for c in step.commands:
                args = [x.replace("{answer}", answer) for x in c.args]
                # re-check right before running (defence in depth)
                check_command(c.tool, args, fastbootd=step.fastbootd, logical_ok=c.logical_ok,
                              allow_unlock=step.unlock)
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
