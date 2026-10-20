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
