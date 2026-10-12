"""Build the self-contained app for the current OS with PyInstaller: dist/curseofdroid-<os>-<arch>.(zip|tar.gz).

One folder with two programs: curseofdroid (CLI) and curseofdroid-gui (window). On macOS the GUI is an .app bundle.
"""

import platform
import shutil
import sys
import tarfile
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
DIST, WORK = ROOT / "dist", ROOT / "build"
OS = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
ARCH = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                                                  platform.machine())
NAME = f"curseofdroid-{OS}-{ARCH}"


# Qt parts the app doesn't use (PyInstaller's PySide6 hooks would otherwise pull some of them in)
QT_UNUSED = ["QtQml", "QtQuick", "QtQuickWidgets", "QtWebEngineCore", "QtWebEngineWidgets", "QtWebChannel",
             "QtMultimedia", "QtPdf", "QtCharts", "QtDataVisualization", "Qt3DCore", "QtSql", "QtNetwork",
             "QtOpenGL", "QtOpenGLWidgets", "QtSvg", "QtDBus", "QtPrintSupport", "QtVirtualKeyboard"]


def build(entry: str, name: str, windowed: bool):
    args = [str(ROOT / "packaging" / entry), "--name", name, "--noconfirm", "--clean",
            "--distpath", str(DIST / NAME), "--workpath", str(WORK), "--specpath", str(WORK),
            "--paths", str(ROOT)]
    if windowed:
        args += ["--windowed", "--collect-submodules", "curseofdroid"]
        args += [x for m in QT_UNUSED for x in ("--exclude-module", f"PySide6.{m}")]
    else:  # the command-line program needs no Qt at all
        args += ["--exclude-module", "PySide6", "--exclude-module", "curseofdroid.gui"]
    PyInstaller.__main__.run(args)


def main():
    shutil.rmtree(DIST / NAME, ignore_errors=True)
    build("cli_entry.py", "curseofdroid", windowed=False)
    build("gui_entry.py", "curseofdroid-gui", windowed=True)
    for f in ("README.md", "LICENSE"):
        shutil.copy(ROOT / f, DIST / NAME / f)
    if OS == "linux":
        out = DIST / f"{NAME}.tar.gz"
        with tarfile.open(out, "w:gz") as t:
            t.add(DIST / NAME, arcname=NAME)
    else:
        out = Path(shutil.make_archive(str(DIST / NAME), "zip", DIST, NAME))
    print(out)


if __name__ == "__main__":
    main()
