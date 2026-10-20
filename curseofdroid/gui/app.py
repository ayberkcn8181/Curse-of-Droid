"""Qt Quick entry point. The existing Widgets workflow remains available during migration."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .. import __version__
from .catalog import Catalog
from .dashboard import Dashboard
from .theme import ThemeManager
from .widgets import MainWindow  # Backwards-compatible import for existing integrations and tests.


class Runtime:
    def __init__(self, app, theme=None, dashboard=None, auto_discover=True, rom_catalog=None, recovery_catalog=None):
        self.app = app
        self.theme = theme if theme is not None else ThemeManager()
        self.dashboard = dashboard if dashboard is not None else Dashboard()
        self.rom_catalog = rom_catalog if rom_catalog is not None else Catalog("rom", self.dashboard)
        self.recovery_catalog = recovery_catalog if recovery_catalog is not None else Catalog("recovery", self.dashboard)
        for catalog in (self.rom_catalog, self.recovery_catalog):
            catalog.operationReported.connect(self.dashboard.record_catalog_event)
        self.windows = []
        if QQuickStyle.name() != "Basic":
            QQuickStyle.setStyle("Basic")
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("theme", self.theme)
        self.engine.rootContext().setContextProperty("backend", self.dashboard)
        self.engine.rootContext().setContextProperty("appVersion", __version__)
        self.engine.rootContext().setContextProperty("autoDiscover", auto_discover)
        self.engine.rootContext().setContextProperty("romCatalog", self.rom_catalog)
        self.engine.rootContext().setContextProperty("recoveryCatalog", self.recovery_catalog)
        self.dashboard.legacyRequested.connect(self.open_legacy)
        self.engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
        if not self.engine.rootObjects():
            raise RuntimeError("Could not load Curse of Droid QML interface")

    def shutdown(self):
        # Destroy QML before its context objects, avoiding null bindings during Python teardown.
        self.engine.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)

    def open_legacy(self, page):
        w = MainWindow()
        selected = self.dashboard.selected_device()
        if selected:
            w.show_devices([selected])
        w.nav.setCurrentRow(page)
        w.setWindowTitle(f"Curse of Droid {__version__} — existing workflows")
        self.windows.append(w)
        w.show()


def main() -> int:
    parser = argparse.ArgumentParser(description="Curse of Droid desktop app")
    parser.add_argument("--classic", action="store_true", help="open the existing Qt Widgets workflows")
    parser.add_argument("--smoke-test", action="store_true", help="load and render QML without USB probes, then exit")
    options = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Curse of Droid")
    app.setOrganizationName("CurseOfDroid")
    app.setApplicationVersion(__version__)
    if options.classic:
        theme = ThemeManager()
        window = MainWindow()
        window.show()
    else:
        runtime = Runtime(app, auto_discover=not options.smoke_test)
        if options.smoke_test:
            def check_render():
                image = runtime.engine.rootObjects()[0].grabWindow()
                app.exit(1 if image.isNull() else 0)
            QTimer.singleShot(250, check_render)
    result = app.exec()
    if not options.classic:
        runtime.shutdown()
    return result


if __name__ == "__main__":
    sys.exit(main())
