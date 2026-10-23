"""Exercise QML's controller API in a fresh process with Qt diagnostics enabled."""
import os
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("PySide6")


def test_runtime_keeps_controller_metadata_stable_and_close_guard_live(tmp_path):
    script = textwrap.dedent('''
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from curseofdroid.gui.app import Runtime
        app = QApplication([])
        runtime = Runtime(app, auto_discover=False)
        window = runtime.engine.rootObjects()[0]
        try:
            QTest.qWait(30)
            # Native enum notification must reach the system-theme receiver.
            events = []
            runtime.theme.setMode("system")
            runtime.theme.changed.connect(lambda: events.append(True))
            app.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Dark)
            assert events
            runtime.downloads.added.emit()
            assert window.property("currentPage") == "downloads"
            runtime.downloads._active = "controlled-active-operation"
            runtime.downloads.changed.emit()
            assert not window.close() and window.isVisible()
        finally:
            runtime.downloads._active = ""
            window.close()
            runtime.shutdown()
    ''')
    env = dict(os.environ, CURSEOFDROID_HOME=str(tmp_path),
               QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
               QT_LOGGING_RULES="qt.pyside.libpyside.warning=true")
    result = subprocess.run([sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Registering dynamic slot" not in result.stderr, result.stderr
    assert "file:" not in result.stderr, result.stderr
