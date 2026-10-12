"""Curse of Droid desktop app: the same core as the CLI, as a step-by-step window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__
from ..catalog.providers import TWRP, find_builds, is_stale
from ..device.detect import Detected, detect
from ..flash.executor import Executor, StepFailed
from ..flash.package import inspect as inspect_package
from ..catalog.deviceinfo import device_info
from ..catalog.gsi import trebledroid_builds, unpack_xz
from ..flash.planner import InstallRequest, PlanError, plan_gsi_install, plan_sideload_install
from ..platform import drivers
from ..platform.net import download
from ..platform.paths import downloads_dir
from ..platform.tools import find_tools, install_platform_tools
from ..vendors import vendor_for
from .bridge import QtUI
from .workers import Job, start

PROFILE_ROWS = [
    ("market_name", "Name"), ("brand", "Brand"), ("model", "Model"), ("codename", "Codename"), ("soc", "SoC"),
    ("mode", "Mode"), ("android_version", "Android"), ("security_patch", "Security patch"),
    ("bootloader_unlocked", "Bootloader unlocked"), ("ab", "A/B slots"), ("dynamic_partitions", "Dynamic partitions"),
    ("treble", "Treble"), ("battery_percent", "Battery %"),
]


def _wrap(*widgets_or_layouts) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    for x in widgets_or_layouts:
        lay.addLayout(x) if not isinstance(x, QWidget) else lay.addWidget(x)
    lay.addStretch(1)
    return w


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Curse of Droid {__version__}")
        self.resize(1000, 680)
        self.device: Detected | None = None
        self.builds = []
        self.ui_bridge = QtUI(self, self.log)

        self.nav = QListWidget()
        self.nav.addItems(["1  Device", "2  Bootloader", "3  ROMs & recoveries", "4  Install"])
        self.nav.setFixedWidth(190)
        self.pages = QStackedWidget()
        for page in (self._device_page(), self._bootloader_page(), self._builds_page(), self._install_page()):
            self.pages.addWidget(page)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.logbox = QPlainTextEdit(readOnly=True)
        self.logbox.setMaximumBlockCount(5000)
        top = QWidget()
        h = QHBoxLayout(top)
        h.addWidget(self.nav)
        h.addWidget(self.pages, 1)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.logbox)
        split.setSizes([520, 160])
        self.setCentralWidget(split)
        self.refresh_tools()

    # ---- helpers ------------------------------------------------------------------------------------------------
    def log(self, text: str) -> None:
        self.logbox.appendPlainText(text)

    def fail(self, msg: str) -> None:
        self.log("ERROR: " + msg)
        QMessageBox.warning(self, "Curse of Droid", msg.split("\n\n")[0])

    # ---- page 1: device -----------------------------------------------------------------------------------------
    def _device_page(self) -> QWidget:
        self.tools_label = QLabel()
        self.tools_btn = QPushButton("Download adb/fastboot (Google platform-tools)")
        self.tools_btn.clicked.connect(self.install_tools)
        self.drivers_label = QLabel(drivers.status().detail)
        self.drivers_label.setWordWrap(True)
        self.detect_btn = QPushButton("Find phone")
        self.detect_btn.clicked.connect(self.run_detect)
        self.device_form = QFormLayout()
        self.device_hint = QLabel("Connect the phone with USB debugging on (or in fastboot/recovery mode), "
                                  "then press Find phone.")
        self.device_hint.setWordWrap(True)
        return _wrap(QLabel("<h2>Device</h2>"), self.tools_label, self.tools_btn, self.drivers_label,
                     self.device_hint, self.detect_btn, self.device_form)

    def refresh_tools(self):
        t = find_tools()
        self.tools_label.setText(f"adb/fastboot: {t.adb.parent if t.adb else 'not found'} ({t.source})")
        self.tools_btn.setVisible(not t.complete)

    def install_tools(self):
        self.tools_btn.setEnabled(False)
        self.log("Downloading platform-tools from dl.google.com …")
        start(Job(lambda p: install_platform_tools(),
                  on_done=lambda _: (self.log("platform-tools installed"), self.refresh_tools()),
                  on_failed=self.fail))

    def run_detect(self):
        tools = find_tools()
        if not tools.complete:
            return self.fail("adb/fastboot missing: download them first.")
        self.detect_btn.setEnabled(False)
        start(Job(lambda p: detect(tools.adb, tools.fastboot), on_done=self.show_devices,
                  on_failed=lambda m: (self.detect_btn.setEnabled(True), self.fail(m))))

    def show_devices(self, found):
        self.detect_btn.setEnabled(True)
        while self.device_form.rowCount():
            self.device_form.removeRow(0)
        found = [d for d in found if d.profile or d.problem]
        if not found:
            self.device = None
            self.device_hint.setText("No phone found. Check the cable, USB debugging and the drivers.")
            return
        if len(found) > 1:
            self.log(f"{len(found)} phones connected; using the first one. Disconnect the others.")
        self.device = found[0]
        if self.device.problem:
            self.device_hint.setText(self.device.problem)
        if not self.device.profile:
            return
        d = self.device.profile.to_dict()
        for key, label in PROFILE_ROWS:
            if d.get(key) not in ("", None, "unknown"):
                self.device_form.addRow(label, QLabel(str(d[key])))
        self.device_hint.setText("Phone found.")
        self.log(f"Found {d.get('market_name') or d['brand'] + ' ' + d['model']} ({d['codename']}) in {d['mode']} mode")
        self.update_bootloader_page()

    # ---- page 2: bootloader -------------------------------------------------------------------------------------
    def _bootloader_page(self) -> QWidget:
        self.bl_text = QLabel("Find the phone first.")
        self.bl_text.setWordWrap(True)
        self.bl_text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.bl_text.setOpenExternalLinks(True)
        self.unlock_btn = QPushButton("Unlock the bootloader (erases the phone)")
        self.unlock_btn.setEnabled(False)
        self.unlock_btn.clicked.connect(self.run_unlock)
        return _wrap(QLabel("<h2>Bootloader</h2>"), self.bl_text, self.unlock_btn)

    def update_bootloader_page(self):
        p = self.device.profile if self.device else None
        if not p:
            return
        if p.bootloader_unlocked == "yes":
            self.bl_text.setText("The bootloader is <b>unlocked</b>. Continue with ROMs &amp; recoveries.")
            self.unlock_btn.setEnabled(False)
            return
        vendor = vendor_for(p)
        info = vendor.info(p)
        parts = [f"<p>Bootloader unlocked: <b>{p.bootloader_unlocked}</b></p><p>{info.summary()}</p><ol>"]
        parts += [f"<li>{s}</li>" for s in info.steps] + ["</ol>"]
        parts += [f"<p><i>Note:</i> {n}</p>" for n in info.notes]
        parts += [f'<p><a href="{u}">{u}</a></p>' for u in info.links]
        self.bl_text.setText("".join(parts))
        self.unlock_plan = vendor.unlock_plan(p) if info.official or info.automated else None
        self.unlock_btn.setEnabled(self.unlock_plan is not None)

    def run_unlock(self):
        plan = self.unlock_plan
        if QMessageBox.warning(self, "Unlock", plan.render() + "\n\nUnlocking ERASES the phone. Continue?",
                               QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self._execute(plan)

    # ---- page 3: builds -----------------------------------------------------------------------------------------
    def _builds_page(self) -> QWidget:
        self.codename_edit = QLineEdit()
        self.codename_edit.setPlaceholderText("codename (empty = the connected phone)")
        find_btn = QPushButton("Search official builds")
        find_btn.clicked.connect(self.run_find)
        row = QHBoxLayout()
        row.addWidget(self.codename_edit, 1)
        row.addWidget(find_btn)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Project", "Type", "Version", "Android", "Date", "File"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dl_btn = QPushButton("Download selected (checksum verified)")
        self.dl_btn.clicked.connect(self.run_download)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        return _wrap(QLabel("<h2>ROMs &amp; recoveries</h2>"), row, self.info_label, self.table, self.dl_btn,
                     self.progress)

    def run_find(self):
        names = [c for c in self.codename_edit.text().split() if c]
        if not names and self.device and self.device.profile:
            names = self.device.profile.codenames
        if not names:
            return self.fail("Enter a codename or find the phone first.")
        self.log(f"Searching for {', '.join(names)} …")
        profile = self.device.profile if self.device and not self.codename_edit.text().strip() else None

        hint = profile.brand if profile else ""
        models = [profile.model] if profile and profile.model else []

        def work(_p):
            info = device_info(names[0], hint, models)
            results, errors = find_builds(names)
            if profile:  # GSIs depend on the connected phone's Treble/ABI/layout, not on a codename
                try:
                    if gsi := trebledroid_builds(profile):
                        results["TrebleDroid GSI"] = gsi
                except Exception as e:
                    errors.append(f"TrebleDroid: {e}")
            return results, errors, info

        start(Job(work, on_done=self.show_builds, on_failed=self.fail))

    def show_builds(self, result):
        results, errors, info = result if len(result) == 3 else (*result, None)
        if info:
            self.info_label.setText(self.device_info_html(info))
        for e in errors:
            self.log("source error: " + e)
        self.builds = [b for builds in results.values() for b in builds[:3]]
        self.table.setRowCount(len(self.builds))
        for r, b in enumerate(self.builds):
            vals = [b.project, b.kind, b.version, b.android, f"{b.date or ''}{' (old)' if is_stale(b) else ''}",
                    b.main.filename]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        self.log(f"{len(results)} projects have builds" if results else
                 "No official builds for this device.")

    @staticmethod
    def device_info_html(info) -> str:
        from html import escape
        title = " ".join(x for x in (info.vendor, info.name) if x) or info.codename
        parts = [f"<b>{escape(title)}</b> — codename <code>{escape(info.codename)}</code>"]
        if info.phones:
            names = []
            for m in info.phones:
                n = m.name if m.name.lower().startswith(m.brand.lower()) else f"{m.brand} {m.name}"
                names.append(f"{escape(n)} <small>({escape(', '.join(m.models[:6]))})</small>")
            parts.append("Sold as: " + "; ".join(names))
        keys = ("Released", "SoC", "RAM", "Storage", "Screen", "Battery")
        specs = " · ".join(f"{k}: {escape(v)}" for k, v in info.specs.items() if k in keys)
        if specs:
            parts.append(specs)
        if not info.phones and not info.specs:
            parts.append("No public catalog entry for this codename.")
        return "<br>".join(parts)

    def run_download(self):
        rows = {i.row() for i in self.table.selectedIndexes()}
        if len(rows) != 1:
            return self.fail("Select one build.")
        b = self.builds[rows.pop()]
        dest = downloads_dir() / b.codename / b.main.filename
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.dl_btn.setEnabled(False)

        def work(progress):
            if b.project == "TWRP":
                TWRP().fill_hash(b)
            path = download(b.main.url, dest, size=b.main.size, hashes=b.main.hashes, headers=b.main.headers,
                            progress=progress)
            return unpack_xz(path) if path.name.endswith(".img.xz") else path

        def done(path):
            self.dl_btn.setEnabled(True)
            self.log(f"Verified: {path}")
            (self.recovery_edit if b.kind == "recovery" else self.rom_edit).setText(str(path))
            if b.kind == "recovery":
                self.recovery_name.setCurrentText(b.project)

        def prog(d, t):
            self.progress.setMaximum(t or 0)
            self.progress.setValue(d if t else 0)

        start(Job(work, on_done=done, on_progress=prog,
                  on_failed=lambda m: (self.dl_btn.setEnabled(True), self.fail(m))))

    # ---- page 4: install ----------------------------------------------------------------------------------------
    def _install_page(self) -> QWidget:
        self.rom_edit, self.recovery_edit = QLineEdit(), QLineEdit()
        self.rom_edit.setPlaceholderText("ROM zip, or a GSI system image (.img)")
        self.extras_edit = QLineEdit()
        self.extras_edit.setPlaceholderText("optional: GApps/other zips, separated by ;")
        self.recovery_name = QComboBox()
        self.recovery_name.addItems(["TWRP", "OrangeFox", "LineageOS Recovery", "other"])
        self.recovery_name.setEditable(True)
        self.flash_rec = QCheckBox("Write the recovery to the phone (default: start it once from the computer)")
        self.keep_data = QCheckBox("Keep data (only for an update of the same ROM)")
        form = QFormLayout()
        for label, edit, filt in (("ROM", self.rom_edit, "ROM zip or GSI image (*.zip *.img)"),
                                  ("Recovery image", self.recovery_edit, "Image (*.img)")):
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            b = QPushButton("…")
            b.clicked.connect(lambda _=False, e=edit, f=filt: self._browse(e, f))
            row.addWidget(b)
            form.addRow(label, row)
        form.addRow("Recovery", self.recovery_name)
        form.addRow("Extras", self.extras_edit)
        self.plan_view = QPlainTextEdit(readOnly=True)
        plan_btn = QPushButton("Show plan")
        plan_btn.clicked.connect(self.make_plan)
        self.install_btn = QPushButton("Install")
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self.run_install)
        btns = QHBoxLayout()
        btns.addWidget(plan_btn)
        btns.addWidget(self.install_btn)
        return _wrap(QLabel("<h2>Install</h2>"), form, self.flash_rec, self.keep_data, btns, self.plan_view)

    def _browse(self, edit: QLineEdit, filt: str):
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", str(downloads_dir()), filt)
        if path:
            edit.setText(path)

    def make_plan(self):
        self.install_btn.setEnabled(False)
        if not (self.device and self.device.profile):
            return self.fail("Find the phone first.")
        if not self.rom_edit.text():
            return self.fail("Choose a ROM zip or GSI image.")
        if self.rom_edit.text().endswith(".img"):
            try:
                self.plan = plan_gsi_install(self.device.profile, Path(self.rom_edit.text()),
                                             wipe_data=not self.keep_data.isChecked())
            except PlanError as e:
                self.plan_view.setPlainText(f"Can't install: {e}")
                return
            self.plan_view.setPlainText(self.plan.render())
            self.install_btn.setEnabled(True)
            return
        req = InstallRequest(
            inspect_package(Path(self.rom_edit.text())),
            recovery=Path(self.recovery_edit.text()) if self.recovery_edit.text() else None,
            recovery_name=self.recovery_name.currentText(), flash_recovery=self.flash_rec.isChecked(),
            wipe_data=not self.keep_data.isChecked(),
            extras=tuple(inspect_package(Path(x.strip())) for x in self.extras_edit.text().split(";") if x.strip()))
        try:
            self.plan = plan_sideload_install(self.device.profile, req)
        except PlanError as e:
            self.plan_view.setPlainText(f"Can't install: {e}")
            return
        self.plan_view.setPlainText(self.plan.render())
        self.install_btn.setEnabled(True)

    def run_install(self):
        if QMessageBox.question(self, "Install", "Start the install? Every risky step asks again.",
                                QMessageBox.Yes | QMessageBox.Cancel) == QMessageBox.Yes:
            self._execute(self.plan)

    # ---- shared -------------------------------------------------------------------------------------------------
    def _execute(self, plan):
        tools = find_tools()
        ex = Executor(tools.adb, tools.fastboot, self.device.serial, self.ui_bridge)
        self.install_btn.setEnabled(False)
        self.unlock_btn.setEnabled(False)

        def failed(msg):
            self.fail(msg)
            self.log("Nothing after the failed step was done.")

        def work(_p):
            try:
                ex.run(plan)
            except StepFailed as e:
                raise RuntimeError(f"Stopped at '{e.step.title}': {e.message}") from None
            return "Done."

        start(Job(work, on_done=lambda m: (self.log(m), QMessageBox.information(self, "Curse of Droid", m)),
                  on_failed=failed))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Curse of Droid")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
