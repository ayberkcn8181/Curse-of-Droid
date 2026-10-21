import os
import threading

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from curseofdroid.device.detect import Detected  # noqa: E402
from curseofdroid.device.profile import DeviceProfile  # noqa: E402
from curseofdroid.flash.plan import Step  # noqa: E402
from curseofdroid.flash.executor import validate  # noqa: E402
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


def test_failed_plan_clears_the_previous_install_action(app, tmp_path, artifact_manifest, monkeypatch):
    import zipfile

    path = tmp_path / "rom.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.bin", b"controlled payload")
        archive.writestr("META-INF/com/android/metadata", "pre-device=lavender\n")
    artifact_manifest(path)
    w = MainWindow()
    w.device = Detected("S1", "android", DeviceProfile(serial="S1", mode="android", codenames=["lavender"],
                                                     bootloader_unlocked="yes", ab="no",
                                                     dynamic_partitions="no"))
    w.rom_edit.setText(str(path))
    w.make_plan()
    assert w.plan is not None and not w.install_btn.isEnabled()
    assert "Automatic sideload is blocked" in w.plan_view.toPlainText()
    messages = []
    monkeypatch.setattr(w, "fail", messages.append)
    w.run_install()
    assert len(messages) == 1 and "Automatic sideload is blocked" in messages[0]
    validate(w.plan)
    path.with_name(path.name + ".manifest.json").unlink()
    w.make_plan()
    assert w.plan is None and not w.install_btn.isEnabled()
    assert "manifest.json" in w.plan_view.toPlainText()
    messages = []
    monkeypatch.setattr(w, "fail", messages.append)
    w.run_install()
    assert messages == ["Create a current installation plan first."]
    w.close()
