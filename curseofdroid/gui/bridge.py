"""The executor's UI protocol for Qt: the executor runs in a worker thread and asks questions through blocking
signals, so every confirmation is a real dialog on the GUI thread."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from ..flash.plan import Step


class QtUI(QObject):
    _info = Signal(str)
    _ask = Signal(str, object, object)  # kind, step, reply box

    def __init__(self, parent: QWidget, log):
        super().__init__()
        self.parent_widget = parent
        self.log = log
        self._info.connect(self.log)
        self._ask.connect(self._on_ask, Qt.QueuedConnection)

    # --- called from the worker thread -------------------------------------------------------------------------
    def info(self, text: str) -> None:
        self._info.emit(text)

    def _round_trip(self, kind: str, step: Step):
        box = {"event": threading.Event(), "value": None}
        self._ask.emit(kind, step, box)
        box["event"].wait()
        return box["value"]

    def confirm(self, step: Step) -> bool:
        return bool(self._round_trip("confirm", step))

    def manual(self, step: Step) -> bool:
        return bool(self._round_trip("manual", step))

    def ask(self, step: Step) -> str:
        return self._round_trip("ask", step) or ""

    # --- GUI thread --------------------------------------------------------------------------------------------
    @Slot(str, object, object)
    def _on_ask(self, kind, step, box):
        try:
            if kind == "confirm":
                text, ok = QInputDialog.getText(
                    self.parent_widget, step.title,
                    f"{step.explain}\n\nThis step is [{step.risk}]. Type yes to continue:")
                box["value"] = ok and text.strip().lower() == "yes"
            elif kind == "manual":
                r = QMessageBox.question(self.parent_widget, step.title,
                                         f"On the phone: {step.manual}\n\nDone?",
                                         QMessageBox.Yes | QMessageBox.Cancel)
                box["value"] = r == QMessageBox.Yes
            else:
                text, ok = QInputDialog.getText(self.parent_widget, step.title, step.ask)
                box["value"] = text if ok else ""
        finally:
            box["event"].set()
