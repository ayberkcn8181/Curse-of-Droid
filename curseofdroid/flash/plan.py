"""A plan is a list of steps the user can read before anything runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Risk = Literal["none", "reboot", "data-loss", "system-write"]
WaitFor = Literal["", "android", "recovery", "sideload", "fastboot", "fastbootd"]


@dataclass
class Command:
    tool: Literal["adb", "fastboot"]
    args: list[str]
    timeout: float = 600
    logical_ok: bool = False  # legacy device: system/vendor are real partitions


@dataclass
class Step:
    title: str
    explain: str  # plain language, shown before the step
    risk: Risk = "none"
    commands: list[Command] = field(default_factory=list)
    wait_for: WaitFor = ""  # device mode to wait for after the commands
    manual: str = ""  # something the user does on the phone; the runner waits for confirmation
    fastbootd: bool = False
    wait_timeout: float = 180  # seconds; the first boot of a new ROM needs much longer


@dataclass
class Plan:
    title: str
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [self.title, ""]
        for w in self.warnings:
            lines.append(f"! {w}")
        if self.warnings:
            lines.append("")
        for i, s in enumerate(self.steps, 1):
            tag = "" if s.risk in ("none", "reboot") else f"  [{s.risk}]"
            lines.append(f"{i}. {s.title}{tag}")
            lines.append(f"   {s.explain}")
            if s.manual:
                lines.append(f"   on the phone: {s.manual}")
            for c in s.commands:
                lines.append(f"   $ {c.tool} {' '.join(c.args)}")
            if s.wait_for:
                lines.append(f"   (waits for {s.wait_for} mode)")
        return "\n".join(lines)
