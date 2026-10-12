"""Run blocking work (adb, downloads, flashing) off the GUI thread."""

from __future__ import annotations

import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)  # done, total (0 = unknown)


class Job(QRunnable):
    """fn(progress) -> result; progress(done, total) may be called from the worker."""

    def __init__(self, fn: Callable, on_done=None, on_failed=None, on_progress=None):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()
        if on_done:
            self.signals.done.connect(on_done)
        if on_failed:
            self.signals.failed.connect(on_failed)
        if on_progress:
            self.signals.progress.connect(on_progress)

    def run(self):
        try:
            result = self.fn(lambda d, t: self.signals.progress.emit(int(d), int(t or 0)))
        except Exception as e:  # shown to the user; the traceback goes to the log
            self.signals.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}")
        else:
            self.signals.done.emit(result)


def start(job: Job) -> None:
    QThreadPool.globalInstance().start(job)
