"""Read-only installation preview. Never constructs an Executor or calls a transport."""
from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot

from ..flash.artifacts import ArtifactError, VerificationCancelled
from ..flash.device_checks import execution_blocker
from ..flash.executor import validate
from ..flash.guard import GuardError
from ..flash.package import inspect
from ..flash.planner import InstallRequest, PlanError, plan_gsi_install, plan_sideload_install
from .workers import Job, start


class InstallationPreview(QObject):
    changed = Signal()
    notice = Signal(str)
    operationReported = Signal(str)
    _progressReceived = Signal(object)  # Python integers: image sizes can exceed Qt's signed 32-bit int.

    def __init__(self, dashboard, parent=None):
        super().__init__(parent if parent is not None else dashboard)
        self.dashboard = dashboard
        self._kind = "rom"
        self._paths = {"main": "", "recovery": "", "addon": ""}
        self._wipe = True
        self._busy = False
        self._closed = False
        self._state = "draft"
        self._message = "Choose files and a device to prepare a read-only plan."
        self._files, self._steps, self._blockers = [], [], []
        self._text = ""
        self._done = self._total = 0
        self._generation = 0
        self._cancel = threading.Event()
        self._job = None
        self._signature = self._selection_signature()
        self.dashboard.changed.connect(self._device_changed)
        self._progressReceived.connect(self._progress)

    def _selection_signature(self):
        selected = self.dashboard.selected_device()
        return json.dumps(dict(busy=self.dashboard.busy,
            device=dict(serial=selected.serial, mode=selected.mode, problem=selected.problem,
                        profile=asdict(selected.profile) if selected.profile else None) if selected else None),
            sort_keys=True)

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(str, notify=changed)
    def state(self): return self._state

    @Property(str, notify=changed)
    def message(self): return self._message

    @Property(str, notify=changed)
    def kind(self): return self._kind

    @Property(bool, notify=changed)
    def wipeData(self): return self._wipe

    @Property("QVariantMap", notify=changed)
    def paths(self): return dict(self._paths)

    @Property("QVariantList", notify=changed)
    def files(self): return list(self._files)

    @Property("QVariantList", notify=changed)
    def steps(self): return list(self._steps)

    @Property("QVariantList", notify=changed)
    def blockers(self): return list(self._blockers)

    @Property(str, notify=changed)
    def planText(self): return self._text

    @Property(float, notify=changed)
    def fraction(self): return self._done / self._total if self._total else 0.0

    @Property(str, notify=changed)
    def progressLabel(self):
        return f"{self._done:,} / {self._total:,} bytes" if self._total else self.tr("Reading package and reference metadata…")

    @Property(bool, notify=changed)
    def hasDevice(self):
        selected = self.dashboard.selected_device()
        return bool(selected and selected.profile and not selected.problem and not self.dashboard.busy
                    and selected.serial and selected.profile.serial == selected.serial
                    and sum(d.serial == selected.serial for d in self.dashboard._found) == 1)

    @Property(bool, notify=changed)
    def canVerify(self): return bool(self.hasDevice and self._paths["main"] and not self.busy and not self._closed)

    @Property("QVariantMap", notify=changed)
    def target(self):
        selected = self.dashboard.selected_device()
        if not selected or not selected.profile:
            return {}
        p = selected.profile
        return dict(name=p.market_name or p.model or p.codename or self.tr("Unidentified device"),
                    serial=p.to_dict()["serial"], codename=p.codename, mode=selected.mode,
                    unlocked=p.bootloader_unlocked, ab=p.ab, slot=p.current_slot or "—")

    def _invalidate(self, message):
        self._generation += 1
        self._cancel.set()
        self._state, self._message = "draft", message
        self._files, self._steps, self._blockers, self._text = [], [], [], ""
        self._done = self._total = 0
        self.changed.emit()

    @Slot()
    def _device_changed(self):
        signature = self._selection_signature()
        if signature != self._signature:
            self._signature = signature
            self._invalidate(self.tr("Device snapshot changed. Verify the files again to rebuild the plan."))

    @Slot(str)
    def setKind(self, kind):
        if self._closed or kind not in {"rom", "gsi"} or kind == self._kind:
            return
        self._kind = kind
        self._paths = {"main": "", "recovery": "", "addon": ""}
        self._invalidate(self.tr("Installation type changed. Choose the matching files."))

    @Slot(bool)
    def setWipeData(self, value):
        if not self._closed and self._wipe != value:
            self._wipe = value
            self._invalidate(self.tr("Data option changed. Rebuild the plan to review its effects."))

    @Slot(str, QUrl)
    def setFile(self, role, url):
        if not url.isLocalFile():
            self.notice.emit(self.tr("Choose a local file on this computer."))
            return
        self.setPath(role, url.toLocalFile())

    @Slot(str, str)
    def setPath(self, role, path):
        if self._closed or role not in self._paths or role != "main" and self._kind != "rom":
            return
        value = str(Path(path).absolute()) if path else ""
        if value != self._paths[role]:
            self._paths[role] = value
            self._invalidate(self.tr("Files changed. Run verification to create a new plan."))

    @Slot()
    def cancel(self):
        if self.busy:
            self._generation += 1
            self._cancel.set()
            self._state = "cancelling"
            self._message = self.tr("Stopping verification after the current file read…")
            self._files, self._steps, self._blockers, self._text = [], [], [], ""
            self.changed.emit()

    @Slot()
    def verify(self):
        if not self.canVerify:
            self.notice.emit(self.tr("Choose a local file and an identified device before verifying."))
            return
        selected = self.dashboard.selected_device()
        profile = copy.deepcopy(selected.profile)
        paths, kind, wipe = dict(self._paths), self._kind, self._wipe
        self._invalidate(self.tr("Reading references and verifying file bytes…"))
        self._generation += 1
        token = self._generation
        cancelled = self._cancel = threading.Event()
        self._busy, self._state = True, "verifying"
        self.changed.emit()

        def work(_unused):
            last = 0.0
            def progress(done, total):
                nonlocal last
                now = time.monotonic()
                if done in (0, total) or now - last >= 0.05:
                    self._progressReceived.emit((token, done, total))
                    last = now
            try:
                if cancelled.is_set(): raise VerificationCancelled("file verification cancelled")
                if kind == "gsi":
                    plan = plan_gsi_install(profile, Path(paths["main"]), wipe_data=wipe)
                else:
                    request = InstallRequest(inspect(Path(paths["main"]), cancelled=cancelled.is_set),
                        recovery=Path(paths["recovery"]) if paths["recovery"] else None,
                        extras=(inspect(Path(paths["addon"]), cancelled=cancelled.is_set),) if paths["addon"] else (), wipe_data=wipe)
                    plan = plan_sideload_install(profile, request)
                validate(plan, progress=progress, cancelled=cancelled.is_set)
                if cancelled.is_set(): raise VerificationCancelled("file verification cancelled")
                return dict(token=token, plan=plan)
            except VerificationCancelled:
                return dict(token=token, cancelled=True)
            except (PlanError, ArtifactError, GuardError, OSError, ValueError) as error:
                message = str(error).replace(profile.serial, "[device]")
                return dict(token=token, error=message[:1200])
            except Exception:
                return dict(token=token, error=self.tr("Preview could not be prepared. Check the files and references."))
        self._job = Job(work, on_done=self._finished, on_failed=self._failed)
        start(self._job)

    @Slot(object)
    def _progress(self, value):
        token, done, total = value
        if self.busy and token == self._generation:
            self._done, self._total = done, total
            self.changed.emit()

    @Slot(object)
    def _finished(self, result):
        self._busy, self._job = False, None
        if self._closed:
            return
        if result["token"] != self._generation:
            if self._state == "cancelling":
                self._state, self._message = "cancelled", self.tr("Verification cancelled. No plan was retained.")
            self.changed.emit()
            return
        if result.get("cancelled"):
            self._state, self._message = "cancelled", self.tr("Verification cancelled. No plan was retained.")
        elif result.get("error"):
            self._state, self._message = "error", result["error"]
            self.operationReported.emit(self.tr("Installation preview stopped: file or target checks did not pass."))
        else:
            plan = result["plan"]
            self._files = [dict(name=a.path.name, kind=a.manifest.kind, size=str(a.manifest.size),
                sha256=a.manifest.sha256, source=a.manifest.source_url,
                devices=", ".join(a.manifest.devices)) for a in plan.artifacts]
            self._steps = [dict(number=i+1, title=s.title, explain=s.explain, risk=s.risk, manual=s.manual,
                                wait=s.wait_for) for i, s in enumerate(plan.steps)]
            self._blockers = [execution_blocker(plan)] if execution_blocker(plan) else []
            self._text = plan.render()
            self._state, self._message = "complete", self.tr("SHA-256 references matched. The plan is ready to review.")
            self.operationReported.emit(self.tr("Read-only installation preview completed. No device operation was run."))
        self.changed.emit()

    @Slot(str)
    def _failed(self, _message):
        # A worker infrastructure failure cannot publish a stale/partly verified plan.
        self._finished(dict(token=self._generation, error=self.tr("Verification worker stopped unexpectedly. Try again.")))

    def close(self):
        if self.busy:
            self.cancel()
            return False
        self._closed = True
        return True
