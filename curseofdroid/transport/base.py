"""Running adb/fastboot. Every command goes through `run()` so it can be logged and faked in tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


@dataclass
class Result:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str], float], Result]


def subprocess_runner(args: Sequence[str], timeout: float) -> Result:
    p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return Result(list(args), p.returncode, p.stdout, p.stderr)


class Tool:
    def __init__(self, exe: Path | str, runner: Runner = subprocess_runner, serial: str | None = None):
        self.exe = str(exe)
        self.runner = runner
        self.serial = serial

    def run(self, *args: str, timeout: float = 30) -> Result:
        base = [self.exe] + (["-s", self.serial] if self.serial else [])
        return self.runner(base + list(args), timeout)
