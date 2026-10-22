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
    parser.add_argument("--pages", nargs="+", choices=["dashboard", "settings", "roms", "recovery", "downloads", "install"], default=["dashboard", "settings"])
    parser.add_argument("--catalog-query", default="", help="run actual providers for this codename before capture")
    parser.add_argument("--download-project", default="", help="queue the first actual result from this project before capture")
    parser.add_argument("--download-kind", choices=["rom", "recovery"], default="recovery")
    args = parser.parse_args()
    if args.download_project and not args.catalog_query:
        parser.error("--download-project requires --catalog-query")
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
                   for mode in ["dark", "light"] for page in args.pages]
        attempts = 0
        queued = False

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
                    catalog_query=args.catalog_query,
                    download_project=args.download_project, downloads=runtime.downloads.rows,
                    catalog={name: dict(state=c.state, rows=c.totalCount, errors=len(c.errors))
                             for name,c in [("roms",runtime.rom_catalog),("recovery",runtime.recovery_catalog)]},
                    method="QQuickWindow.grabWindow, actual backend, no injected data; offscreen software rendering",
                ), indent=2) + "\n")
                app.quit()

        def await_discovery():
            nonlocal attempts, queued
            attempts += 1
            if runtime.dashboard.busy or runtime.rom_catalog.busy or runtime.recovery_catalog.busy or runtime.downloads.busy:
                if attempts > 6000:
                    print("Discovery did not finish within 300 seconds", file=sys.stderr)
                    app.exit(1)
                else:
                    QTimer.singleShot(50, await_discovery)
            else:
                if args.download_project and not queued:
                    catalog = runtime.recovery_catalog if args.download_kind == "recovery" else runtime.rom_catalog
                    row = next((r for r in catalog.rows if r["project"] == args.download_project), None)
                    if not row:
                        print("No actual catalog result for requested download project", file=sys.stderr)
                        app.exit(1)
                        return
                    queued = True
                    catalog.select(row["id"])
                    catalog.queueSelected()
                    QTimer.singleShot(50, await_discovery)
                    return
                restored = next((r for r in runtime.downloads.rows if r["project"] == args.download_project and r["state"] == "needs-check"), None)
                if args.download_project and restored:
                    runtime.downloads.recheck(restored["id"])
                    QTimer.singleShot(50, await_discovery)
                    return
                # Let actual transient notifications expire before the first screenshot.
                QTimer.singleShot(6200 if args.download_project else 0, capture)

        if args.catalog_query:
            if "roms" in args.pages or (args.download_project and args.download_kind == "rom"):
                runtime.rom_catalog.search(args.catalog_query)
            if "recovery" in args.pages or (args.download_project and args.download_kind == "recovery"):
                runtime.recovery_catalog.search(args.catalog_query)
        QTimer.singleShot(50, await_discovery)
        result = app.exec()
        runtime.shutdown()
        return result


if __name__ == "__main__":
    sys.exit(main())
