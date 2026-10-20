"""Capture actual Qt Quick windows; never inject example devices or change user preferences.

QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, qVersion
from PySide6.QtWidgets import QApplication

from .app import Runtime
from .theme import ThemeManager


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/screenshots"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([sys.argv[0]])
    with tempfile.TemporaryDirectory(prefix="cod-capture-") as directory:
        settings = QSettings(str(Path(directory) / "appearance.ini"), QSettings.IniFormat)
        theme = ThemeManager(settings)
        theme.setAnimations(False)
        theme.setMode("dark")
        runtime = Runtime(app, theme=theme)
        window = runtime.engine.rootObjects()[0]
        targets = [(mode, page, size) for size in [(1260, 900), (920, 680)]
                   for mode in ["dark", "light"] for page in ["dashboard", "settings"]]
        attempts = 0

        def capture():
            mode, page, size = targets[0]
            theme.setMode(mode)
            window.resize(*size)
            window.setProperty("currentPage", page)
            QTimer.singleShot(80, save)

        def save():
            mode, page, size = targets.pop(0)
            suffix = "-small" if size[0] == 920 else ""
            image = window.grabWindow()
            path = args.output / f"{page}-{mode}{suffix}.png"
            if image.isNull() or not image.save(str(path)):
                print(f"Could not capture {path}", file=sys.stderr)
                app.exit(1)
                return
            print(path)
            if targets:
                capture()
            else:
                (args.output / "capture.json").write_text(json.dumps(dict(
                    platform=platform.platform(), python=platform.python_version(), qt=qVersion(),
                    state=runtime.dashboard.state, tools_ready=runtime.dashboard.toolsReady,
                    devices=len(runtime.dashboard.devices),
                    method="QQuickWindow.grabWindow, actual backend, no injected data; offscreen software rendering",
                ), indent=2) + "\n")
                app.quit()

        def await_discovery():
            nonlocal attempts
            attempts += 1
            if runtime.dashboard.busy:
                if attempts > 1200:
                    print("Discovery did not finish within 60 seconds", file=sys.stderr)
                    app.exit(1)
                else:
                    QTimer.singleShot(50, await_discovery)
            else:
                capture()

        QTimer.singleShot(50, await_discovery)
        result = app.exec()
        runtime.shutdown()
        return result


if __name__ == "__main__":
    sys.exit(main())
