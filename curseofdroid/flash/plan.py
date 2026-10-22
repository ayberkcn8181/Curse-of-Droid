"""A plan is a list of steps the user can read before anything runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .artifacts import ArtifactRequirement

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
    unlock: bool = False  # bootloader unlock command(s) from a vendor flow (guard: allow_unlock)
    ask: str = ""  # question for the user; the answer replaces "{answer}" in this step's commands
    show_output: bool = False  # print the command output to the user (e.g. Motorola unlock data)


@dataclass(frozen=True)
class InstallTarget:
    serial: str
    codenames: tuple[str, ...]
    ab: str = "unknown"
    current_slot: str = ""
    dynamic_partitions: str = "unknown"

    @classmethod
    def from_profile(cls, profile):
        return cls(profile.serial, tuple(profile.codenames), profile.ab, profile.current_slot,
                   profile.dynamic_partitions)


@dataclass
class Plan:
    title: str
    steps: list[Step]
    warnings: list[str] = field(default_factory=list)
    artifacts: tuple[ArtifactRequirement, ...] = ()
    target: InstallTarget | None = None

    def render(self) -> str:
        lines = [self.title, ""]
        if self.target:
            serial = self.target.serial
            masked = serial[:2] + "…" + serial[-2:] if len(serial) > 4 else "…"
            lines.extend([f"Target: {', '.join(self.target.codenames)} (serial {masked})", ""])
        for w in self.warnings:
            lines.append(f"! {w}")
        if self.warnings:
            lines.append("")
        if self.artifacts:
            lines.append("Required file checks (repeated before execution and each file operation):")
            for artifact in self.artifacts:
                lines.append(f"   {artifact.path.name}: {artifact.manifest.size} bytes")
                lines.append(f"   SHA-256 {artifact.manifest.sha256}")
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
