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


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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
