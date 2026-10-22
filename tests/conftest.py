"""Keep one QApplication alive for the entire GUI suite, including module boundaries."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")


@pytest.fixture(scope="session")
def app():
    # Optional GUI dependencies must not cause ordinary backend tests to be skipped.
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application
    assert QThreadPool.globalInstance().waitForDone(10000), "Qt workers still running at session shutdown"
    application.processEvents()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


import hashlib
import json


@pytest.fixture
def artifact_manifest():
    def write(path, kind="rom", **overrides):
        content = path.read_bytes()
        document = dict(version=1, filename=path.name, kind=kind, size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                        source_url="https://publisher.example/releases/checksums.txt", devices=["lavender"])
        if kind == "gsi":
            document.update(abi="arm64-v8a", layout="system-as-root")
        document.update(overrides)
        path.with_name(path.name + ".manifest.json").write_text(json.dumps(document), encoding="utf-8")
        return document
    return write
