"""Read-only QML view model; all transport and catalog work stays in Python services."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QCoreApplication, QObject, Property, Signal, Slot

from ..catalog.providers import ALL_PROVIDERS
from ..device.detect import detect
from ..platform.tools import find_tools, install_platform_tools
from .workers import Job, start


class Dashboard(QObject):
    changed = Signal()
    notice = Signal(str)
    legacyRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent if parent is not None else QCoreApplication.instance())
        self._busy = False
        self._state = "idle"
        self._scanned = False
        self._error = ""
        self._found = []
        self._selected = -1
        self._preferred_serial = None
        self._events = []
        self._job = None
        self._tools = find_tools()

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(bool, notify=changed)
    def scanned(self):
        return self._scanned

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(bool, notify=changed)
    def toolsReady(self):
        return self._tools.complete

    @Property(str, notify=changed)
    def toolsSource(self):
        return self._tools.source

    @Property(int, constant=True)
    def romProjects(self):
        return sum(p.kind == "rom" for p in ALL_PROVIDERS)

    @Property("QVariantList", notify=changed)
    def devices(self):
        # Only an index and redacted identity cross the presentation boundary.
        rows = []
        for i, d in enumerate(self._found):
            p = d.profile
            name = (p.market_name or p.model or p.codename) if p else self.tr("Unidentified device")
            serial = d.serial[:2] + "…" + d.serial[-2:] if len(d.serial) > 4 else "…"
            rows.append(dict(index=i, label=f"{name} · {serial} · {d.mode}"))
        return rows

    @Property(int, notify=changed)
    def selectedIndex(self):
        return self._selected

    @Property("QVariantMap", notify=changed)
    def device(self):
        if 0 <= self._selected < len(self._found):
            d = self._found[self._selected]
            return d.profile.to_dict() if d.profile else {}
        return {}

    @Property("QVariantList", notify=changed)
    def activity(self):
        return list(reversed(self._events))

    @Property(str, notify=changed)
    def connection(self):
        if self._busy:
            return self.tr("Working…")
        if 0 <= self._selected < len(self._found):
            return self._found[self._selected].mode
        return self.tr("No device selected")

    def _event(self, text, status="info"):
        self._events.append(dict(time=datetime.now().astimezone().strftime("%H:%M:%S"),
                                 message=text, status=status))
        self._events = self._events[-100:]

    def _start(self, fn, receiver):
        self._busy = True
        self._error = ""
        self._job = Job(fn, on_done=receiver, on_failed=self._failed)
        self.changed.emit()
        start(self._job)

    @Slot()
    def refresh(self):
        if self._busy:
            return
        self._tools = find_tools()
        if 0 <= self._selected < len(self._found):
            self._preferred_serial = self._found[self._selected].serial
        self._found = []
        self._selected = -1
        self._scanned = False
        if not self._tools.complete:
            self._state = "missing"
            self._error = ""
            self._event(self.tr("Platform-tools not found. Install them to discover devices."))
            self.changed.emit()
            return
        self._state = "scanning"
        self._event(self.tr("Read-only USB discovery started."))
        adb, fastboot = self._tools.adb, self._tools.fastboot
        self._start(lambda _progress: detect(adb, fastboot), self._detected)

    @Slot(object)
    def _detected(self, found):
        self._busy = False
        self._job = None
        self._found = found
        self._scanned = True
        self._selected = next((i for i, d in enumerate(found) if d.serial == self._preferred_serial), -1)
        if len(found) == 1:
            self._selected = 0
        self._update_selection()
        self._event(self.tr("Discovery finished: %n device(s).", "", len(found)))
        self.changed.emit()

    def _update_selection(self):
        self._error = ""
        if not self._found:
            self._state = "disconnected"
        elif self._selected < 0:
            self._state = "selection"
        else:
            d = self._found[self._selected]
            self._error = d.problem
            self._state = "error" if d.problem else "connected"

    @Slot(int)
    def selectDevice(self, index):
        if self._busy or not 0 <= index < len(self._found):
            return
        self._selected = index
        self._preferred_serial = self._found[index].serial
        self._update_selection()
        self._event(self.tr("Selected device changed."))
        self.changed.emit()

    @Slot()
    def installTools(self):
        if not self._busy:
            self._event(self.tr("Downloading Google platform-tools over HTTPS."))
            self._start(lambda _p: install_platform_tools(), self._tools_installed)

    @Slot(object)
    def _tools_installed(self, tools):
        self._busy = False
        self._job = None
        self._tools = tools
        self._event(self.tr("Platform-tools installed."), "success")
        self.refresh()

    @Slot(str)
    def _failed(self, message):
        self._busy = False
        self._job = None
        self._state = "error"
        # Tracebacks can include raw transport identifiers. Do not export them to QML.
        summary = message.split("\n\n", 1)[0]
        for d in self._found:
            if d.serial:
                summary = summary.replace(d.serial, "[device]")
        self._error = summary
        self._found = []
        self._selected = -1
        self._event(self.tr("Operation failed. Check connection and platform-tools."), "error")
        self.changed.emit()
        self.notice.emit(self._error)

    @Slot(str)
    def record_catalog_event(self, text):
        self._event(text)
        self.changed.emit()

    @Slot(int)
    def openLegacy(self, page):
        if not self._busy and page in (0, 1, 2, 3):
            self.legacyRequested.emit(page)

    def selected_device(self):
        return self._found[self._selected] if 0 <= self._selected < len(self._found) else None
