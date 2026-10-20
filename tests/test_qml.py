"""Real Qt Quick rendering plus controlled transport integration; never use a physical device."""
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from curseofdroid.device.detect import Detected, detect
from curseofdroid.device.profile import DeviceProfile
from curseofdroid.gui.app import Runtime
from curseofdroid.gui.dashboard import Dashboard
from curseofdroid.gui.theme import ACCENTS, PALETTES, ThemeManager
from curseofdroid.platform.tools import Tools
from curseofdroid.transport.base import Result


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class SystemHints(QObject):
    colorSchemeChanged = Signal()

    def __init__(self):
        super().__init__()
        self.scheme = Qt.ColorScheme.Light

    def colorScheme(self):
        return self.scheme

    def change(self, scheme):
        self.scheme = scheme
        self.colorSchemeChanged.emit()


def preferences(path):
    return QSettings(str(path), QSettings.IniFormat)


def wait_for(app, predicate):
    for _ in range(200):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    pytest.fail("Qt operation did not complete within 1 second")


def test_theme_system_live_override_and_restart(app, tmp_path):
    path = tmp_path / "preferences.ini"
    hints = SystemHints()
    manager = ThemeManager(preferences(path), hints)
    assert manager.mode == "system" and not manager.dark
    hints.change(Qt.ColorScheme.Dark)
    assert manager.dark
    manager.setMode("light")
    hints.change(Qt.ColorScheme.Light)
    hints.change(Qt.ColorScheme.Dark)
    assert not manager.dark  # explicit choice wins
    manager.setMode("dark")
    manager.setAccent("teal")
    manager.setAnimations(False)
    manager.setScale(1.15)
    restored = ThemeManager(preferences(path), hints)
    assert restored.mode == "dark" and restored.dark
    assert restored.accentName == "teal" and restored.scale == 1.15
    assert restored.animations is False
    restored.setMode("system")
    hints.change(Qt.ColorScheme.Light)
    assert not restored.dark


def test_invalid_preferences_fall_back_without_invalid_colors(app, tmp_path):
    s = preferences(tmp_path / "settings.ini")
    for key, value in dict(mode="garbage", accent="garbage", scale="invalid").items():
        s.setValue("appearance/" + key, value)
    manager = ThemeManager(s, SystemHints())
    assert manager.mode == "system" and manager.accentName == "purple" and manager.scale == 1
    manager.setMode("invalid")
    manager.setAccent("#ffffff")
    manager.setScale(12)
    assert manager.mode == "system" and manager.accentName == "purple" and manager.scale == 1


def luminance(value):
    c = QColor(value)
    channels = [c.redF(), c.greenF(), c.blueF()]
    r, g, b = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    x, y = sorted([luminance(a), luminance(b)])
    return (y + .05) / (x + .05)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_design_text_contrast(mode):
    c = PALETTES[mode]
    for text in ("text", "secondary", "success", "warning", "error"):
        for surface in ("background", "surface", "elevated"):
            assert contrast(c[text], c[surface]) >= 4.5, (mode, text, surface)
    for normal, hover in ACCENTS.values():
        assert contrast(c["onAccent"], normal) >= 4.5
        assert contrast(c["onAccent"], hover) >= 4.5


@pytest.fixture
def model(app, monkeypatch, tmp_path):
    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    monkeypatch.setattr("curseofdroid.gui.dashboard.find_tools", lambda: Tools(Path("adb"), Path("fastboot"), "PATH"))
    return Dashboard()


def test_real_detection_pipeline_and_disconnect(app, model, monkeypatch):
    fixture = Path("tests/fixtures/huawei_atu_l21_lineage17_getprop.txt").read_text()
    calls = []

    def runner(args, timeout):
        calls.append(list(args))
        if args == ["adb", "devices", "-l"]:
            out = "List of devices attached\nTESTSERIAL device\n"
        elif args == ["adb", "-s", "TESTSERIAL", "shell", "getprop"]:
            out = fixture
        elif args[0] == "adb" and args[-2] == "shell":
            out = "73"
        else:
            out = ""
        return Result(list(args), 0, out, "")

    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: detect(a, f, runner))
    model.refresh()
    wait_for(app, lambda: not model.busy)
    assert model.state == "connected"
    assert model.device["codename"] == "msm8937_64"
    assert model.device["battery_percent"] == 73
    assert model.device["serial"] != "TESTSERIAL"
    assert ["adb", "-s", "TESTSERIAL", "shell", "getprop"] in calls
    assert all("flash" not in c and "erase" not in c and "reboot" not in c for c in calls)
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: [])
    model.refresh()
    assert model.device == {}  # clear stale data at start
    wait_for(app, lambda: not model.busy)
    assert model.state == "disconnected" and model.selectedIndex == -1


def test_multiple_devices_require_selection_and_preserve_unknown(app, model, monkeypatch):
    devices = [Detected("ABC123", "android", DeviceProfile(model="One")),
               Detected("DEF456", "fastboot", DeviceProfile(model="Two", mode="fastboot"))]
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: devices)
    model.refresh()
    wait_for(app, lambda: not model.busy)
    assert model.state == "selection" and not model.device
    model.selectDevice(1)
    assert model.device["model"] == "Two"
    assert model.device["bootloader_unlocked"] == "unknown"
    model.selectDevice(99)
    assert model.selectedIndex == 1
    model.refresh()
    wait_for(app, lambda: not model.busy)
    assert model.device["model"] == "Two"


def test_unauthorized_and_failure_finish_on_gui_thread(app, model, monkeypatch):
    devices = [Detected("ABC123", "android", None, "unauthorized: allow USB debugging")]
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: devices)
    model.refresh()
    wait_for(app, lambda: not model.busy)
    assert model.state == "error" and "unauthorized" in model.error
    assert model.device == {}
    completed = QSignalSpy(model.notice)

    def fail(*_):
        raise RuntimeError("controlled transport failure")

    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", fail)
    model.refresh()
    wait_for(app, lambda: not model.busy)
    assert model.state == "error" and "controlled transport failure" in model.error
    assert completed.count() == 1
    assert model.thread() == QApplication.instance().thread()


def test_missing_tools_and_install_completion(app, model, monkeypatch):
    missing = Tools(None, None, "missing")
    monkeypatch.setattr("curseofdroid.gui.dashboard.find_tools", lambda: missing)
    model.refresh()
    assert model.state == "missing" and not model.toolsReady
    ready = Tools(Path("adb"), Path("fastboot"), "curseofdroid")
    monkeypatch.setattr("curseofdroid.gui.dashboard.install_platform_tools", lambda: ready)
    monkeypatch.setattr("curseofdroid.gui.dashboard.find_tools", lambda: ready)
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: [])
    model.installTools()
    wait_for(app, lambda: not model.busy)
    assert model.toolsReady and model.state == "disconnected"


@pytest.fixture
def runtime(app, model, monkeypatch, tmp_path):
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: [])
    theme = ThemeManager(preferences(tmp_path / "appearance.ini"), SystemHints())
    theme.setAnimations(False)
    r = Runtime(app, theme, model)
    wait_for(app, lambda: not model.busy)
    yield r
    r.engine.rootObjects()[0].close()
    r.shutdown()
    app.processEvents()


def test_qml_startup_navigation_keyboard_and_real_theme_click(app, runtime):
    window = runtime.engine.rootObjects()[0]
    assert window.isVisible()
    window.requestActivate()
    QTest.qWait(20)
    QTest.keyClick(window, Qt.Key_Comma, Qt.ControlModifier)
    assert window.property("currentPage") == "settings"
    def find_item(item, name):
        if item.objectName() == name:
            return item
        return next((found for child in item.childItems() if (found := find_item(child, name))), None)
    button = find_item(window.contentItem(), "theme-dark")
    assert button is not None
    center = button.mapToScene(button.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
    assert runtime.theme.mode == "dark"
    QTest.keyClick(window, Qt.Key_1, Qt.ControlModifier)
    assert window.property("currentPage") == "dashboard"
    QTest.keyClick(window, Qt.Key_Tab)
    assert window.activeFocusItem() is not None


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("size", [(1260, 900), (920, 680)])
def test_qml_render_all_pages_no_qml_errors(app, runtime, mode, size, capfd):
    window = runtime.engine.rootObjects()[0]
    runtime.theme.setMode(mode)
    window.resize(*size)
    for page in ("dashboard", "device", "activity", "settings"):
        window.setProperty("currentPage", page)
        QTest.qWait(30)
        image = window.grabWindow()
        assert not image.isNull()
        assert image.width() == size[0] and image.height() == size[1]
        assert image.pixelColor(size[0] - 2, size[1] - 2).name() == runtime.theme.colors["background"].lower()
    errors = capfd.readouterr().err
    assert "file:" not in errors, errors


def test_existing_workflows_keep_selected_backend_device(app, runtime, monkeypatch):
    selected = Detected("ABC123", "android", DeviceProfile(model="Selected phone", brand="oppo"))
    runtime.dashboard._detected([selected])
    runtime.dashboard.openLegacy(2)
    assert len(runtime.windows) == 1
    w = runtime.windows[0]
    assert w.device is selected and w.nav.currentRow() == 2
    runtime.dashboard.openLegacy(99)
    assert len(runtime.windows) == 1
    w.close()


def test_preferences_survive_a_new_process(app, tmp_path):
    import json
    import subprocess
    import sys

    s = preferences(tmp_path / "preferences.ini")
    theme = ThemeManager(s, SystemHints())
    theme.setMode("dark")
    theme.setAccent("blue")
    env = dict(os.environ, CURSEOFDROID_HOME=str(tmp_path))
    code = ("import json; from PySide6.QtWidgets import QApplication; "
            "from curseofdroid.gui.theme import ThemeManager; "
            "a=QApplication([]); t=ThemeManager(); "
            "print(json.dumps([t.mode,t.dark,t.accentName]))")
    result = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                            capture_output=True, check=True, timeout=10)
    assert json.loads(result.stdout) == ["dark", True, "blue"]


def test_gui_remains_responsive_and_defers_close_while_working(app, runtime, monkeypatch):
    import threading
    from PySide6.QtCore import QTimer

    release = threading.Event()
    monkeypatch.setattr("curseofdroid.gui.dashboard.detect", lambda a, f: (release.wait(2), [])[1])
    window = runtime.engine.rootObjects()[0]
    ticks = []
    try:
        runtime.dashboard.refresh()
        QTimer.singleShot(5, lambda: ticks.append(True))
        wait_for(app, lambda: bool(ticks))
        assert runtime.dashboard.busy
        assert not window.close()
        assert window.isVisible()
    finally:
        release.set()
        wait_for(app, lambda: not runtime.dashboard.busy)


def test_qml_entrypoint_smoke_has_no_shutdown_errors(tmp_path):
    import subprocess
    import sys

    result = subprocess.run([sys.executable, "-m", "curseofdroid.gui.app", "--smoke-test"],
                            env=dict(os.environ, CURSEOFDROID_HOME=str(tmp_path)),
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "file:" not in result.stderr, result.stderr


def test_scale_dropdown_is_interactive(app, runtime, capfd):
    window = runtime.engine.rootObjects()[0]
    window.resize(1260, 900)
    window.setProperty("currentPage", "settings")
    window.requestActivate()
    QTest.qWait(20)
    combo = window.findChild(QObject, "scaleSelector")
    assert combo is not None
    point = combo.mapToScene(combo.boundingRect().center()).toPoint()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
    QTest.keyClick(window, Qt.Key_Down)
    QTest.keyClick(window, Qt.Key_Return)
    assert runtime.theme.scale == 1.15
    assert "file:" not in capfd.readouterr().err
