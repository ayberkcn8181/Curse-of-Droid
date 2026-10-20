"""Actual file writes, shared backend checks and QML events with controlled publisher HTTP."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QSignalSpy, QTest

from curseofdroid.catalog.base import Artifact, Build
from curseofdroid.catalog.providers import LineageOS
from curseofdroid.gui.app import Runtime
from curseofdroid.gui.catalog import Catalog
from curseofdroid.gui.dashboard import Dashboard
from curseofdroid.gui.downloads import DownloadManager
from curseofdroid.gui.theme import ThemeManager
from curseofdroid.platform import net
from test_downloads import BODY, HASHES, URL, Response, respond


def wait(app, condition):
    for _ in range(600):
        app.processEvents()
        if condition():
            return
        QTest.qWait(5)
    pytest.fail("Download worker did not finish")


def build(filename="rom.zip", **kwargs):
    return Build("Source", "rom", "phone", "1", None,
                 [Artifact(filename, URL, size=len(BODY), hashes=dict(HASHES), **kwargs)])


@pytest.fixture
def manager(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    controller = DownloadManager()
    yield controller
    controller.pauseAll()
    wait(app, lambda: not controller.busy)
    controller.close()


def test_actual_backend_download_private_snapshot_dedupe_and_history(app, manager, monkeypatch):
    calls = respond(monkeypatch, Response(Content_Length="6"))
    source = build()
    manager.enqueue(source)
    source.main.url = "https://changed.example.org/other.zip"
    wait(app, lambda: not manager.busy)
    row = manager.rows[0]
    assert row["state"] == "complete" and row["done"] == "6" and row["fraction"] == 1
    assert row["integrity"] == "Publisher checksum matched: sha256"
    assert "url" not in row and "headers" not in row and len(calls) == 1
    item = manager._items[0]
    assert manager._path(item).read_bytes() == BODY
    manager.enqueue(build())
    assert len(manager.rows) == 1 and len(calls) == 1
    manager.remove(row["id"])
    assert manager.rows == [] and manager._path(item).read_bytes() == BODY
    assert json.loads(manager.manifest.read_text())["items"] == []


def test_failed_hash_and_retry_use_real_backend(app, manager, monkeypatch):
    respond(monkeypatch, Response(b"xxxxxx", Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    row = manager.rows[0]
    assert row["state"] == "failed" and "sha256 mismatch" in row["error"]
    assert not manager._path(manager._items[0]).exists()
    respond(monkeypatch, Response(Content_Length="6"))
    manager.resume(row["id"])
    wait(app, lambda: not manager.busy)
    assert manager.rows[0]["state"] == "complete"


def test_pause_all_stops_queue_and_restart_never_auto_resumes(app, manager, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Slow(Response):
        def read(self, size=-1):
            entered.set()
            release.wait(3)
            return super().read(size)

    calls = respond(monkeypatch, Slow(Content_Length="6"))
    try:
        manager.enqueue(build())
        wait(app, entered.is_set)
        manager.enqueue(build("second.zip"))
        assert manager.rows[0]["state"] == "queued" and manager.busy
        manager.pauseAll()
        assert manager.rows[1]["state"] == "pausing"
    finally:
        release.set()
        wait(app, lambda: not manager.busy)
    assert all(r["state"] == "paused" for r in manager.rows) and len(calls) == 1
    manager.close()
    restored = DownloadManager()
    assert not restored.busy and all(r["state"] == "paused" for r in restored.rows)
    assert len(calls) == 1
    respond(monkeypatch, Response(Content_Length="6"))
    restored.resume(restored.rows[0]["id"])
    wait(app, lambda: not restored.busy)
    assert restored.completedCount == 1
    restored.close()


def test_queue_advances_after_first_real_transfer_without_overlap(app, manager, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class Slow(Response):
        def read(self, size=-1):
            entered.set()
            release.wait(3)
            return super().read(size)

    calls = respond(monkeypatch, Slow(Content_Length="6"), Response(Content_Length="6"))
    try:
        manager.enqueue(build())
        wait(app, entered.is_set)
        manager.enqueue(build("second.zip"))
        assert len(calls) == 1 and manager.rows[0]["state"] == "queued"
    finally:
        release.set()
        wait(app, lambda: not manager.busy and manager.completedCount == 2)
    assert len(calls) == 2 and all(manager._path(i).read_bytes() == BODY for i in manager._items)


def test_restored_completion_requires_recheck_and_detects_local_tampering(app, manager, monkeypatch):
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    manager.close()
    restored = DownloadManager()
    assert restored.rows[0]["state"] == "needs-check" and restored.completedCount == 0
    path = restored._path(restored._items[0])
    path.write_bytes(b"xxxxxx")
    restored.recheck(restored.rows[0]["id"])
    wait(app, lambda: not restored.busy)
    assert restored.rows[0]["state"] == "failed" and restored.rows[0]["integrity"] == "Not checked"
    respond(monkeypatch, Response(Content_Length="6"))
    restored.resume(restored.rows[0]["id"])
    wait(app, lambda: not restored.busy)
    assert path.read_bytes() == BODY and restored.completedCount == 1
    restored.close()


def test_missing_integrity_metadata_stays_explicit_after_restart(app, manager, monkeypatch):
    source = build()
    source.main.size, source.main.hashes = None, {}
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(source)
    wait(app, lambda: not manager.busy)
    assert "no publisher checksum or expected size" in manager.rows[0]["integrity"]
    manager.close()
    restored = DownloadManager()
    assert restored.rows[0]["state"] == "needs-check" and not restored.rows[0]["canCheck"]
    restored.recheck(restored.rows[0]["id"])
    wait(app, lambda: not restored.busy)
    assert "no publisher checksum or expected size" in restored.rows[0]["integrity"]
    restored.close()


@pytest.mark.parametrize("mutation", [
    lambda b: setattr(b.main, "url", "http://example.org/file"),
    lambda b: setattr(b.main, "filename", "../rom.zip"),
    lambda b: setattr(b.main, "direct", False),
    lambda b: setattr(b.main, "hashes", {"sha256": "invalid"}),
    lambda b: setattr(b.main, "headers", {"Authorization": "private-token"}),
])
def test_bad_artifacts_never_reach_network(app, manager, monkeypatch, mutation):
    calls = respond(monkeypatch)
    notice = QSignalSpy(manager.notice)
    source = build()
    mutation(source)
    manager.enqueue(source)
    assert not manager.busy and manager.rows == [] and not calls and notice.count() == 1


@pytest.mark.parametrize("payload", [b"{broken", b'{"version":2,"items":[]}',
    b'{"version":1,"items":[{"id":"../bad"}]}'])
def test_corrupt_history_is_preserved_without_overwrite(app, manager, monkeypatch, payload):
    manager.manifest.write_bytes(payload)
    restored = DownloadManager()
    calls = respond(monkeypatch)
    restored.enqueue(build())
    assert restored.storageError and not restored.busy and not calls
    assert restored.manifest.read_bytes() == payload


def test_invalid_saved_checksum_does_not_crash_or_overwrite_history(app, manager, monkeypatch):
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    manager.close()
    document = json.loads(manager.manifest.read_text())
    document["items"][0]["source"]["hashes"] = {"sha256":"bad"}
    payload = json.dumps(document)
    manager.manifest.write_text(payload)
    restored = DownloadManager()
    restored.enqueue(build())
    assert restored.storageError and restored.rows == [] and restored.manifest.read_text() == payload
    restored.close()


def test_queue_permission_failure_is_visible_and_does_not_start_network(app, tmp_path, monkeypatch):
    blocked = tmp_path / "blocked"
    blocked.write_text("preserve")
    manager = DownloadManager(root=tmp_path / "downloads", manifest=blocked / "queue.json")
    calls = respond(monkeypatch)
    manager.enqueue(build())
    assert manager.storageError and not manager.rows and not manager.busy and not calls
    assert blocked.read_text() == "preserve"


def test_second_instance_cannot_overwrite_active_history(app, manager, monkeypatch):
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    original = manager.manifest.read_bytes()
    second = DownloadManager()
    assert second.storageError and "read-only" in second.storageError
    second.enqueue(build("other.zip"))
    assert not second.busy and second.manifest.read_bytes() == original
    second.close()


def test_twrp_fetches_actual_checksum_parser_before_download(app, manager, monkeypatch):
    calls = []

    def serve(req, timeout):
        calls.append(req.full_url)
        if req.full_url.endswith(".sha256"):
            return Response((HASHES["sha256"] + " rom.img\n").encode())
        return Response(Content_Length="6")

    monkeypatch.setattr(net, "urlopen", serve)
    source = build("rom.img")
    source.project, source.kind, source.main.hashes = "TWRP", "recovery", {}
    source.main.headers = {"Referer": URL + ".html"}
    manager.enqueue(source)
    wait(app, lambda: not manager.busy)
    assert calls == [URL + ".sha256", URL]
    assert manager.rows[0]["state"] == "complete" and manager.rows[0]["hashes"] == "sha256"
    assert "Referer" not in str(manager.rows)


def test_history_restores_in_a_new_process_without_network(app, manager, monkeypatch):
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    code = ("import json; from PySide6.QtWidgets import QApplication; "
            "from curseofdroid.gui.downloads import DownloadManager; "
            "a=QApplication([]); m=DownloadManager(); print(json.dumps([m.busy,m.rows[0]['state'],m.completedCount]))")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=15, env=dict(os.environ), check=True)
    assert json.loads(result.stdout) == [False, "needs-check", 0]


def test_only_recorded_download_folders_can_be_opened(app, manager, monkeypatch):
    respond(monkeypatch, Response(Content_Length="6"))
    manager.enqueue(build())
    wait(app, lambda: not manager.busy)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u) or True)
    manager.openFolder("https://arbitrary.example.org")
    assert not opened
    manager.openFolder(manager.rows[0]["id"])
    assert opened[0].isLocalFile() and Path(opened[0].toLocalFile()).resolve() == manager._path(manager._items[0]).parent.resolve()


def find_item(item, name):
    if item.objectName() == name:
        return item
    return next((r for c in item.childItems() if (r := find_item(c, name))), None)


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_qml_catalog_download_route_and_recheck_with_actual_file(app, manager, tmp_path, monkeypatch, mode, capfd):
    from curseofdroid.gui import downloads
    checked = []
    original_verify = downloads.verify

    def observe_check(*args, **kwargs):
        checked.append(args[0])
        return original_verify(*args, **kwargs)

    monkeypatch.setattr(downloads, "verify", observe_check)
    dashboard = Dashboard()
    responses = {
        LineageOS.API.format(c="phone"): '{"name":"Phone"}',
        LineageOS.API.format(c="phone") + "/builds": json.dumps([{"version":"23", "files":[{
            "filename":"rom.zip", "url":URL, "size":6, "sha256":HASHES["sha256"]}]}]),
    }
    catalog = Catalog("rom", dashboard, [LineageOS], lambda u: responses[u])
    theme = ThemeManager(QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    theme.setMode(mode)
    theme.setAnimations(False)
    runtime = Runtime(app, theme, dashboard, auto_discover=False, rom_catalog=catalog, downloads=manager)
    window = runtime.engine.rootObjects()[0]
    window.setProperty("currentPage", "roms")
    window.resize(1260, 900)
    window.requestActivate()
    respond(monkeypatch, Response(Content_Length="6"))
    try:
        catalog.search("phone")
        wait(app, lambda: not catalog.busy)
        assert "_source" not in catalog.rows[0]
        QTest.qWait(30)
        detail = find_item(window.contentItem(), "build-details-" + str(catalog.rows[0]["id"]))
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, detail.mapToScene(detail.boundingRect().center()).toPoint())
        QTest.qWait(30)
        button = find_item(window.contentItem(), "queueSelectedDownload")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
        wait(app, lambda: not manager.busy and manager.completedCount == 1)
        assert window.property("currentPage") == "downloads"
        for size in [(1260,900), (920,680)]:
            window.resize(*size)
            QTest.qWait(30)
            assert not window.grabWindow().isNull()
        window.resize(1260, 900)
        QTest.qWait(20)
        recheck = find_item(window.contentItem(), "recheck-" + manager.rows[0]["id"])
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, recheck.mapToScene(recheck.boundingRect().center()).toPoint())
        wait(app, lambda: not manager.busy and len(checked) == 1)
        assert manager.completedCount == 1 and checked[0].read_bytes() == BODY
        assert "file:" not in capfd.readouterr().err
    finally:
        wait(app, lambda: not manager.busy)
        window.close()
        runtime.shutdown()


def test_qml_responsive_pause_and_close_with_large_counters(app, manager, tmp_path, monkeypatch):
    from curseofdroid.gui import downloads
    entered, release = threading.Event(), threading.Event()

    def transfer(url, dest, **kwargs):
        kwargs["progress"](4 << 30, 8 << 30)
        entered.set()
        release.wait(3)
        if kwargs["cancelled"]():
            raise net.DownloadCancelled()
        raise AssertionError("Expected pause")

    monkeypatch.setattr(downloads, "download", transfer)
    runtime = Runtime(app, dashboard=Dashboard(), auto_discover=False, downloads=manager)
    window = runtime.engine.rootObjects()[0]
    ticks = []
    try:
        manager.enqueue(build())
        wait(app, entered.is_set)
        QTimer.singleShot(5, lambda: ticks.append(True))
        wait(app, lambda: bool(ticks) and manager.rows[0]["done"] == str(4 << 30))
        assert not window.close() and window.isVisible()
        assert manager.rows[0]["fraction"] == .5
        manager.pauseAll()
    finally:
        release.set()
        wait(app, lambda: not manager.busy)
        window.close()
        runtime.shutdown()
    assert manager.rows[0]["state"] == "paused"
