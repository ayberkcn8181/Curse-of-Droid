"""Catalog integration through existing provider parsers, controlled HTTP and actual QML events."""
import datetime as dt
import json
import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from curseofdroid.catalog.base import Artifact, Build, Provider
from curseofdroid.catalog.providers import ALL_PROVIDERS, ENDED, ArrowOS, GrapheneOS, LineageOS, OrangeFox, TWRP
from curseofdroid.device.detect import Detected
from curseofdroid.device.profile import DeviceProfile
from curseofdroid.gui.app import Runtime
from curseofdroid.gui.catalog import Catalog, build_row, https_link
from curseofdroid.gui.dashboard import Dashboard
from curseofdroid.gui.theme import ThemeManager
from curseofdroid.platform.net import NotFound


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait(app, condition):
    for _ in range(300):
        app.processEvents()
        if condition():
            return
        QTest.qWait(5)
    pytest.fail("Catalog worker did not complete")


@pytest.fixture
def dashboard(app, tmp_path, monkeypatch):
    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    return Dashboard()


@pytest.fixture
def responses():
    recent = int(dt.datetime.now(dt.timezone.utc).timestamp())
    return {
        LineageOS.API.format(c="testphone"): json.dumps({"name": "Test phone", "info_url": "https://wiki.lineageos.org/devices/testphone/"}),
        LineageOS.API.format(c="testphone") + "/builds": json.dumps([{
            "version": "23.0", "datetime": recent, "type": "nightly", "files": [
                {"filename": "lineage-testphone.zip", "url": "https://example.org/rom.zip", "sha256": "a"*64},
                {"filename": "recovery.img", "url": "https://example.org/recovery.img", "sha256": "b"*64},
                {"filename": "boot.img", "url": "https://example.org/boot.img"}]}]),
        ArrowOS.BASE + "/arrow-13.1_gapps_builds_official.json": json.dumps({"testphone": [{
            "filename": "arrow-testphone.zip", "version": "13.1", "date": "2020-01-01", "sha256": "c"*64}]}),
        "https://releases.grapheneos.org/testphone-stable": f"2026102000 {recent}",
        TWRP.BASE.format(c="testphone"): '<a href="/testphone/twrp-3.7.0_12-0-testphone.img.html">TWRP</a>',
        OrangeFox.API + "/releases/?codename=testphone&type=stable&sort=date_desc&limit=10": json.dumps({"data":[{
            "_id":"release", "device_id":"testphone", "filename":"OrangeFox-testphone.zip", "version":"R12",
            "date":recent, "md5":"d"*32, "mirrors":{"DL":"https://example.org/fox.zip"}}]}),
    }


def fetcher(responses):
    def fetch(url):
        if url not in responses:
            raise NotFound(url)
        return responses[url]
    return fetch


class Broken(Provider):
    name = "Broken source"
    homepage = "https://example.org"

    def builds(self, codename):
        raise ValueError("controlled metadata failure")


def test_full_provider_registry_preserved(dashboard):
    rom = Catalog("rom", dashboard)
    recovery = Catalog("recovery", dashboard)
    assert rom.projects == sorted(p.name for p in ALL_PROVIDERS if p.kind == "rom")
    assert rom.providerCount == 19
    assert set(recovery.projects) == {"TWRP", "OrangeFox", "LineageOS Recovery"}


def test_real_provider_pipeline_filters_and_failed_source_isolation(app, dashboard, responses):
    catalog = Catalog("rom", dashboard, [LineageOS, ArrowOS, GrapheneOS, Broken], fetcher(responses))
    catalog.search("testphone")
    wait(app, lambda: not catalog.busy)
    assert catalog.state == "partial" and catalog.totalCount == 3
    assert catalog.completedProviders == 4 and len(catalog.errors) == 1
    assert set(catalog.androidVersions) == {"16", "13"}
    assert next(r for r in catalog.rows if r["project"] == "ArrowOS")["ended"]
    assert "own web installer" in next(r for r in catalog.rows if r["project"] == "GrapheneOS")["notes"]
    catalog.setFilters("", "", "13", "old", "newest")
    assert [r["project"] for r in catalog.rows] == ["ArrowOS"]
    catalog.select(catalog.rows[0]["id"])
    catalog.setFilters("", "LineageOS", "", "", "project")
    assert catalog.selected == {} and len(catalog.rows) == 1
    catalog.setFilters("not present", "", "", "", "oldest")
    assert catalog.rows == [] and catalog.totalCount == 3


def test_recovery_images_not_guessed_from_boot(app, dashboard, responses):
    catalog = Catalog("recovery", dashboard, [LineageOS, TWRP, OrangeFox], fetcher(responses))
    catalog.search("testphone")
    wait(app, lambda: not catalog.busy)
    assert catalog.state == "ready" and catalog.totalCount == 3
    assert {r["project"] for r in catalog.rows} == {"TWRP", "OrangeFox", "LineageOS Recovery"}
    lineage = next(r for r in catalog.rows if r["project"] == "LineageOS Recovery")
    assert lineage["filename"] == "recovery.img" and "partition/method" in lineage["notes"]
    assert all(r["filename"] != "boot.img" for r in catalog.rows)
    fox = next(r for r in catalog.rows if r["project"] == "OrangeFox")
    assert fox["hashKinds"] == "MD5" and fox["hashes"] == {"md5":"d"*32}
    catalog.setFilters("", "TWRP", "", "unknown", "newest")
    assert len(catalog.rows) == 1 and catalog.rows[0]["date"] == ""


@pytest.mark.parametrize("value", ["", "../phone", "a/b", "a?x=1", "a b", "a\nb", "x"*65, "https://a.com"])
def test_codename_rejected_before_network(app, dashboard, value):
    calls = []
    catalog = Catalog("rom", dashboard, [LineageOS], lambda url: calls.append(url))
    notice = QSignalSpy(catalog.notice)
    catalog.search(value)
    assert not catalog.busy and calls == [] and notice.count() == 1


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "http://example.org/x",
    "https://user:password@example.org/a", "https://example.org/a\nb", "https://127.0.0.1/a",
    "https://192.168.1.1/a", "https://localhost/a", "https://example.org:invalid/", "https://example.org/\\x"])
def test_untrusted_links_rejected(url):
    assert https_link(url) == ""


def test_only_backend_selected_https_links_open(app, dashboard, responses, monkeypatch):
    catalog = Catalog("rom", dashboard, [LineageOS], fetcher(responses))
    catalog.search("testphone")
    wait(app, lambda: not catalog.busy)
    catalog.select(catalog.rows[0]["id"])
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True)
    catalog.openSelectedLink("source")
    assert opened == ["https://example.org/rom.zip"]
    catalog.openSelectedLink("https://evil.example/")
    assert len(opened) == 1
    old_id = catalog.rows[0]["id"]
    catalog.search("testphone")
    wait(app, lambda: not catalog.busy)
    catalog.select(old_id)
    assert not catalog.selected  # IDs are not reused across searches.


def test_selected_device_change_discards_inflight_results(app, dashboard, responses):
    dashboard._detected([Detected("SERIAL", "android", DeviceProfile(codenames=["testphone"]))])
    release, entered = threading.Event(), threading.Event()
    original = fetcher(responses)

    def blocked(url):
        entered.set()
        release.wait(2)
        return original(url)

    catalog = Catalog("rom", dashboard, [LineageOS], blocked)
    try:
        catalog.searchSelected()
        wait(app, entered.is_set)
        dashboard._detected([])
        assert catalog.state == "invalidated" and catalog.rows == []
    finally:
        release.set()
        wait(app, lambda: not catalog.busy)
    assert catalog.state == "invalidated" and catalog.rows == []


def test_cancel_between_http_requests_no_stale_results(app, dashboard, responses):
    release, entered = threading.Event(), threading.Event()
    calls = []

    def blocked(url):
        calls.append(url)
        entered.set()
        release.wait(2)
        return fetcher(responses)(url)

    catalog = Catalog("rom", dashboard, [LineageOS, GrapheneOS], blocked)
    try:
        catalog.search("testphone")
        wait(app, entered.is_set)
        catalog.search("differentphone")  # Cannot start overlapping jobs.
        catalog.cancel()
        assert catalog.busy and catalog.state == "cancelling"
    finally:
        release.set()
        wait(app, lambda: not catalog.busy)
    assert catalog.state == "cancelled" and len(calls) == 1 and catalog.rows == []


def test_bad_record_isolated_and_missing_metadata_is_unknown(app, dashboard):
    class Malformed(Provider):
        name = "Malformed"
        homepage = "https://example.org"

        def builds(self, codename):
            return [Build(self.name, "rom", codename, "", None, []),
                    Build(self.name, "rom", codename, "", None, [Artifact("file.zip", "file:///x", hashes={"sha256":"bad"})])]

    catalog = Catalog("rom", dashboard, [Malformed], lambda u: "")
    catalog.search("phone")
    wait(app, lambda: not catalog.busy)
    assert catalog.state == "partial" and catalog.totalCount == 1
    row = catalog.rows[0]
    assert row["age"] == "unknown" and row["hashes"] == {} and row["sourceUrl"] == ""


def find_item(item, name):
    if item.objectName() == name:
        return item
    return next((found for child in item.childItems() if (found := find_item(child, name))), None)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_real_qml_catalog_search_details_and_both_routes(app, dashboard, responses, tmp_path, mode, capfd):
    rom = Catalog("rom", dashboard, [LineageOS, ArrowOS, GrapheneOS], fetcher(responses))
    recovery = Catalog("recovery", dashboard, [LineageOS, TWRP, OrangeFox], fetcher(responses))
    theme = ThemeManager(QSettings(str(tmp_path / "prefs.ini"), QSettings.IniFormat))
    theme.setMode(mode)
    theme.setAnimations(False)
    runtime = Runtime(app, theme, dashboard, auto_discover=False, rom_catalog=rom, recovery_catalog=recovery)
    window = runtime.engine.rootObjects()[0]
    window.resize(1260, 900)
    window.setProperty("currentPage", "roms")
    window.requestActivate()
    QTest.qWait(30)
    try:
        field = find_item(window.contentItem(), "romCodename")
        field.setProperty("text", "testphone")
        field.forceActiveFocus()
        QTest.keyClick(window, Qt.Key_Return)
        wait(app, lambda: not rom.busy and rom.totalCount == 3)
        QTest.qWait(40)
        button = find_item(window.contentItem(), "build-details-" + str(rom.rows[0]["id"]))
        assert button is not None
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, button.mapToScene(button.boundingRect().center()).toPoint())
        assert rom.selected and not window.grabWindow().isNull()
        QTest.keyClick(window, Qt.Key_Escape)
        for size in [(1260,900), (920,680)]:
            window.resize(*size)
            for page in ("roms", "recovery"):
                window.setProperty("currentPage", page)
                QTest.qWait(20)
                assert not window.grabWindow().isNull()
        recovery.search("testphone")
        wait(app, lambda: not recovery.busy)
        assert recovery.totalCount == 3
        QTest.qWait(30)
        assert "file:" not in capfd.readouterr().err
    finally:
        window.close()
        runtime.shutdown()


def test_results_stream_before_all_providers_finish(app, dashboard, responses):
    release, entered = threading.Event(), threading.Event()
    original = fetcher(responses)

    def staged(url):
        if "grapheneos" in url:
            entered.set()
            release.wait(2)
        return original(url)

    catalog = Catalog("rom", dashboard, [LineageOS, GrapheneOS], staged)
    try:
        catalog.search("testphone")
        wait(app, lambda: entered.is_set() and catalog.completedProviders == 1)
        assert catalog.busy and catalog.totalCount == 1
        assert catalog.rows[0]["project"] == "LineageOS"
    finally:
        release.set()
        wait(app, lambda: not catalog.busy)
    assert catalog.totalCount == 2


def test_catalog_jobs_keep_gui_responsive_and_defer_close(app, dashboard, responses, tmp_path):
    release, entered = threading.Event(), threading.Event()

    def blocked(url):
        entered.set()
        release.wait(2)
        return fetcher(responses)(url)

    catalog = Catalog("rom", dashboard, [LineageOS], blocked)
    theme = ThemeManager(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    runtime = Runtime(app, theme, dashboard, auto_discover=False, rom_catalog=catalog)
    window = runtime.engine.rootObjects()[0]
    try:
        catalog.search("testphone")
        wait(app, entered.is_set)
        assert not window.close() and window.isVisible()
        catalog.cancel()
    finally:
        release.set()
        wait(app, lambda: not catalog.busy)
        window.close()
        runtime.shutdown()


def test_future_dates_and_sorting_keep_unknown_last(app, dashboard):
    today = dt.date.today()

    class Dates(Provider):
        name = "Dates"
        homepage = "https://example.org"

        def builds(self, codename):
            return [Build(self.name, "rom", codename, str(i), date, [Artifact("rom.zip", "https://example.org/rom.zip")])
                    for i,date in enumerate([None, today-dt.timedelta(days=200), today, today+dt.timedelta(days=20)])]

    catalog = Catalog("rom", dashboard, [Dates], lambda url: "")
    catalog.search("phone")
    wait(app, lambda: not catalog.busy)
    assert catalog.rows[-1]["age"] == "unknown"
    catalog.setFilters("", "", "", "future", "newest")
    assert len(catalog.rows) == 1 and catalog.rows[0]["version"] == "3"
    catalog.setFilters("", "", "", "", "oldest")
    assert catalog.rows[0]["version"] == "1" and catalog.rows[-1]["age"] == "unknown"


def test_qml_provider_errors_can_be_expanded(app, dashboard, responses, tmp_path, capfd):
    catalog = Catalog("rom", dashboard, [LineageOS, Broken], fetcher(responses))
    theme = ThemeManager(QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    runtime = Runtime(app, theme, dashboard, auto_discover=False, rom_catalog=catalog)
    window = runtime.engine.rootObjects()[0]
    window.resize(1260, 900)
    window.setProperty("currentPage", "roms")
    window.requestActivate()
    try:
        catalog.search("testphone")
        wait(app, lambda: not catalog.busy)
        QTest.qWait(30)
        toggle = find_item(window.contentItem(), "toggle-romErrors")
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, toggle.mapToScene(toggle.boundingRect().center()).toPoint())
        assert find_item(window.contentItem(), "romErrors").property("expanded")
        QTest.qWait(20)
        assert "file:" not in capfd.readouterr().err
    finally:
        window.close()
        runtime.shutdown()
