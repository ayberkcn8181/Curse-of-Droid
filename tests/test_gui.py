import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from curseofdroid.device.detect import Detected  # noqa: E402
from curseofdroid.device.profile import DeviceProfile  # noqa: E402
from curseofdroid.flash.plan import Step  # noqa: E402
from curseofdroid.gui.app import MainWindow  # noqa: E402


def test_window_pages_and_device(app):
    w = MainWindow()
    p = DeviceProfile(mode="android", brand="OPPO", model="CPH2801", codenames=["OP628FL1"],
                      bootloader_unlocked="no")
    w.show_devices([Detected("X", "android", p)])
    assert w.pages.count() == 4
    assert "no official unlock method" in w.bl_text.text()
    assert not w.unlock_btn.isEnabled()


def test_confirm_from_worker_thread_needs_typed_yes(app, monkeypatch):
    w = MainWindow()
    answers = iter([("yes", True), ("y", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    step = Step("Erase", "x", "data-loss")
    results = []

    def worker():
        results.append(w.ui_bridge.confirm(step))
        results.append(w.ui_bridge.confirm(step))

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        app.processEvents()
    assert results == [True, False]  # "y" is not enough


def test_legacy_download_handles_large_progress_without_claiming_hash(app, tmp_path, monkeypatch):
    from curseofdroid.catalog.base import Artifact, Build
    from curseofdroid.gui import widgets

    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    monkeypatch.setattr(widgets, "start", lambda job: job.run())

    def transfer(url, dest, **kwargs):
        kwargs["progress"](4 << 30, 8 << 30)
        return dest

    monkeypatch.setattr(widgets, "download", transfer)
    w = MainWindow()
    w.show_builds(({"Source": [Build("Source", "rom", "phone", "1", None,
                                       [Artifact("rom.zip", "https://example.org/rom.zip")])]}, []))
    w.table.selectRow(0)
    w.run_download()
    assert w.progress.maximum() == 100 and w.progress.value() == 50
    assert "no publisher checksum or expected size" in w.logbox.toPlainText()
