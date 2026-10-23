"""Real temporary bytes + actual QML/worker events. No device operation is allowed."""
import json
import threading
import zipfile

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings, QThread, QUrl, Qt
from PySide6.QtTest import QTest

from curseofdroid.device.detect import Detected
from curseofdroid.device.profile import DeviceProfile
from curseofdroid.flash.artifacts import VerificationCancelled, require_artifact, verify_artifact
from curseofdroid.flash.executor import validate
from curseofdroid.gui.app import Runtime
from curseofdroid.gui.dashboard import Dashboard
from curseofdroid.gui.installation import InstallationPreview
from curseofdroid.gui.theme import ThemeManager

SERIAL = "PRIVATE-SERIAL-12345678"


def wait(app, condition):
    for _ in range(800):
        app.processEvents()
        if condition(): return
        QTest.qWait(5)
    pytest.fail("Preview worker did not finish")


def device(**overrides):
    fields = dict(serial=SERIAL, mode="android", model="Controlled test device", codenames=["lavender"],
                  bootloader_unlocked="yes", battery_percent=80, treble="yes", abi="arm64-v8a", ab="yes",
                  current_slot="a", dynamic_partitions="yes", system_as_root="yes")
    fields.update(overrides)
    return Detected(SERIAL, fields["mode"], DeviceProfile(**fields))


@pytest.fixture
def dashboard(app):
    model = Dashboard()
    model._detected([device()])
    return model


@pytest.fixture
def preview(app, dashboard, monkeypatch):
    # Any accidental execution/transport call is a test failure.
    def forbidden(*args, **kwargs): pytest.fail("Read-only preview touched device execution")
    monkeypatch.setattr("curseofdroid.flash.executor.Executor.run", forbidden)
    monkeypatch.setattr("curseofdroid.transport.base.Tool.run", forbidden)
    controller = InstallationPreview(dashboard)
    yield controller
    controller.cancel()
    wait(app, lambda: not controller.busy)
    assert controller.close()


@pytest.fixture
def image(tmp_path, artifact_manifest):
    path = tmp_path / "system.img"
    path.write_bytes(b"actual controlled image bytes" * 100)
    artifact_manifest(path, "gsi")
    return path


def rom_file(tmp_path, artifact_manifest, name="rom.zip", kind="rom"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.bin", b"controlled OTA payload")
        archive.writestr("META-INF/com/android/metadata", "pre-device=lavender\n")
    artifact_manifest(path, kind)
    return path


def prepare(preview, image):
    preview.setKind("gsi")
    preview.setFile("main", QUrl.fromLocalFile(str(image)))
    assert preview.canVerify
    preview.verify()


def test_actual_gsi_hash_plan_and_blocker_with_no_device_execution(app, preview, image, monkeypatch):
    threads = []
    def observed(plan, **kwargs):
        threads.append(QThread.currentThread())
        return validate(plan, **kwargs)
    monkeypatch.setattr("curseofdroid.gui.installation.validate", observed)
    prepare(preview, image)
    wait(app, lambda: not preview.busy)
    assert preview.state == "complete" and threads[0] != app.thread()
    assert preview.files[0]["name"] == image.name and preview.files[0]["size"] == str(image.stat().st_size)
    assert len(preview.files[0]["sha256"]) == 64 and preview.fraction == 1
    assert "Aggregate fastboot -w is blocked" in preview.blockers[0]
    assert "flash system" in preview.planText and SERIAL not in preview.planText
    assert SERIAL not in str(preview.target) and preview.target["slot"] == "a"
    assert any(s["risk"] == "data-loss" for s in preview.steps)


def test_real_rom_recovery_and_addon_each_have_their_own_reference(app, preview, tmp_path, artifact_manifest):
    rom = rom_file(tmp_path, artifact_manifest)
    addon = rom_file(tmp_path, artifact_manifest, "addon.zip", "addon")
    recovery = tmp_path / "recovery.img"
    recovery.write_bytes(b"controlled recovery bytes")
    artifact_manifest(recovery, "recovery")
    for role, path in (("main", rom), ("recovery", recovery), ("addon", addon)):
        preview.setPath(role, str(path))
    preview.verify()
    wait(app, lambda: not preview.busy)
    assert preview.state == "complete" and {f["kind"] for f in preview.files} == {"rom", "recovery", "addon"}
    assert "Automatic sideload is blocked" in preview.blockers[0]
    assert any("once" in s["title"] for s in preview.steps)
    assert preview.fraction == 1 and SERIAL not in preview.planText


@pytest.mark.parametrize("problem", ["no-reference", "bad-hash", "wrong-device", "bad-json", "compressed"])
def test_failed_file_checks_never_publish_a_plan(app, preview, image, problem):
    reference = image.with_name(image.name + ".manifest.json")
    if problem == "no-reference": reference.unlink()
    elif problem == "bad-json": reference.write_text("not JSON")
    elif problem in {"bad-hash", "wrong-device"}:
        data = json.loads(reference.read_text())
        data["sha256" if problem == "bad-hash" else "devices"] = "0" * 64 if problem == "bad-hash" else ["oriole"]
        reference.write_text(json.dumps(data))
    else: image = image.with_suffix(".img.xz")
    prepare(preview, image)
    wait(app, lambda: not preview.busy)
    assert preview.state == "error" and preview.files == preview.steps == preview.blockers == []
    assert preview.planText == "" and SERIAL not in preview.message


@pytest.mark.parametrize("change", ["file", "kind", "wipe", "device", "disconnect", "profile"])
def test_every_input_or_target_change_discards_the_old_result(app, preview, image, dashboard, change):
    prepare(preview, image)
    wait(app, lambda: not preview.busy)
    assert preview.state == "complete"
    if change == "file": preview.setPath("main", str(image.with_name("different.img")))
    elif change == "kind": preview.setKind("rom")
    elif change == "wipe": preview.setWipeData(False)
    elif change == "disconnect": dashboard._detected([])
    elif change == "profile": dashboard._found[0].profile.current_slot = "b"; dashboard.changed.emit()
    else:
        other = device(serial="OTHER-SERIAL")
        other.serial = "OTHER-SERIAL"
        dashboard._detected([other])
    assert preview.state == "draft" and not preview.planText and not preview.files and not preview.steps


@pytest.mark.parametrize("change", ["cancel", "file", "device", "close"])
def test_cancellation_and_changes_while_hashing_ignore_late_success(app, preview, image, dashboard, monkeypatch, change):
    entered, release = threading.Event(), threading.Event()
    def paused(plan, **kwargs):
        entered.set()
        release.wait(4)
        return validate(plan, **kwargs)
    monkeypatch.setattr("curseofdroid.gui.installation.validate", paused)
    prepare(preview, image)
    wait(app, entered.is_set)
    try:
        assert preview.busy
        if change == "cancel": preview.cancel()
        elif change == "file": preview.setPath("main", str(image.with_name("new.img")))
        elif change == "device": dashboard._detected([])
        else: assert not preview.close()
        assert not preview.canVerify and not preview.files
    finally:
        release.set()
        wait(app, lambda: not preview.busy)
    assert preview.state == ("cancelled" if change in {"cancel", "close"} else "draft")
    assert not preview.planText and not preview.files and not preview.steps


def test_cancel_after_worker_success_but_before_queued_delivery_discards_result(app, preview, image, monkeypatch):
    finished = threading.Event()
    def observed(plan, **kwargs):
        validate(plan, **kwargs)
        finished.set()
    monkeypatch.setattr("curseofdroid.gui.installation.validate", observed)
    prepare(preview, image)
    assert finished.wait(3)
    # Keep GUI events queued until cancellation increments the generation.
    preview.cancel()
    wait(app, lambda: not preview.busy)
    assert preview.state == "cancelled" and not preview.files and not preview.planText


def test_large_byte_progress_uses_python_integers_and_gui_thread(app, preview, image, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr("curseofdroid.gui.installation.validate", lambda *a, **k: (entered.set(), release.wait(4)))
    prepare(preview, image)
    wait(app, entered.is_set)
    try:
        preview._progressReceived.emit((preview._generation, 1 << 40, 1 << 41))
        assert preview.fraction == 0.5 and "1,099,511,627,776" in preview.progressLabel
        preview.cancel()
    finally:
        release.set()
        wait(app, lambda: not preview.busy)


def test_failed_retry_clears_the_previously_valid_snapshot(app, preview, image):
    prepare(preview, image)
    wait(app, lambda: not preview.busy)
    assert preview.files
    image.write_bytes(b"x" * image.stat().st_size)
    preview.verify()
    assert not preview.files and not preview.steps and not preview.planText
    wait(app, lambda: not preview.busy)
    assert preview.state == "error"


def test_missing_ambiguous_or_unidentified_selection_cannot_start(app, dashboard, image):
    for found in ([], [Detected(SERIAL, "android", None, "unauthorized")], [device(), device()]):
        dashboard._detected(found)
        controller = InstallationPreview(dashboard)
        controller.setPath("main", str(image))
        assert not controller.canVerify
        controller.verify()
        assert not controller.busy and not controller.files
        assert controller.close()


def test_remote_file_urls_are_refused_and_kind_change_clears_hidden_files(preview, image):
    preview.setFile("main", QUrl("https://publisher.example/rom.zip"))
    assert not preview.paths["main"]
    preview.setPath("recovery", str(image))
    preview.setKind("gsi")
    assert all(not p for p in preview.paths.values())
    preview.setPath("recovery", str(image))
    assert not preview.paths["recovery"]


def test_hash_callback_cancellation_is_not_a_valid_verdict(image):
    requirement = require_artifact(image, "gsi")
    cancel = threading.Event()
    calls = []
    def progress(done, total):
        calls.append((done, total))
        if done: cancel.set()
    with pytest.raises(VerificationCancelled):
        verify_artifact(requirement, progress=progress, cancelled=cancel.is_set)
    assert calls[0] == (0, requirement.manifest.size) and calls[-1][0] == requirement.manifest.size


def find_item(item, name):
    if item.objectName() == name: return item
    return next((found for child in item.childItems() if (found := find_item(child, name))), None)


@pytest.mark.parametrize("mode", ["dark", "light"])
@pytest.mark.parametrize("size", [(1260, 900), (920, 680)])
def test_actual_qml_installation_page_both_themes_and_sizes(app, dashboard, tmp_path, monkeypatch, image, mode, size, capfd):
    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    theme = ThemeManager(QSettings(str(tmp_path / "appearance.ini"), QSettings.IniFormat))
    theme.setMode(mode)
    theme.setAnimations(False)
    runtime = Runtime(app, theme=theme, dashboard=dashboard, auto_discover=False)
    try:
        window = runtime.engine.rootObjects()[0]
        window.resize(*size)
        window.setProperty("currentPage", "install")
        QTest.qWait(50)
        button = find_item(window.contentItem(), "installGsiType")
        assert button is not None
        center = button.mapToScene(button.boundingRect().center()).toPoint()
        QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
        assert runtime.installation.kind == "gsi"
        runtime.installation.setPath("main", str(image))
        runtime.installation.verify()
        wait(app, lambda: not runtime.installation.busy)
        assert runtime.installation.files and runtime.installation.steps
        for tab in (0, 1, 2):
            page = find_item(window.contentItem(), "installationPage")
            page.setProperty("reviewTab", tab)
            QTest.qWait(20)
            shot = window.grabWindow()
            assert not shot.isNull() and (shot.width(), shot.height()) == size
        errors = capfd.readouterr().err
        assert "file:" not in errors and "ReferenceError" not in errors, errors
    finally:
        runtime.shutdown()
        app.processEvents()


def test_duplicate_serial_cannot_be_previewed_even_when_manually_selected(app, dashboard, image):
    dashboard._detected([device(), device()])
    dashboard.selectDevice(0)
    controller = InstallationPreview(dashboard)
    controller.setPath("main", str(image))
    assert not controller.hasDevice and not controller.canVerify
    controller.close()


def test_progress_notifications_are_delivered_on_gui_thread(app, preview, image):
    threads = []
    preview.changed.connect(lambda: threads.append(QThread.currentThread()))
    prepare(preview, image)
    wait(app, lambda: not preview.busy)
    assert threads and all(thread == app.thread() for thread in threads)


def test_actual_window_defers_close_during_verification_and_remains_responsive(app, dashboard, image, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    entered, release = threading.Event(), threading.Event()
    def paused(plan, **kwargs):
        entered.set()
        release.wait(4)
        return validate(plan, **kwargs)
    monkeypatch.setattr("curseofdroid.gui.installation.validate", paused)
    theme = ThemeManager(QSettings(str(tmp_path / "appearance.ini"), QSettings.IniFormat))
    runtime = Runtime(app, theme=theme, dashboard=dashboard, auto_discover=False)
    window = runtime.engine.rootObjects()[0]
    try:
        prepare(runtime.installation, image)
        wait(app, entered.is_set)
        assert not window.close() and window.isVisible()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        wait(app, lambda: bool(ticks))
        runtime.installation.cancel()
    finally:
        release.set()
        wait(app, lambda: not runtime.installation.busy)
        assert not runtime.installation.files
        window.close()
        runtime.shutdown()
        app.processEvents()


def test_cancel_during_real_package_metadata_stops_before_hashing(app, preview, tmp_path, artifact_manifest, monkeypatch):
    from curseofdroid.flash import package
    path = tmp_path / "metadata.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("payload.bin", b"unread")
        archive.writestr(package.META, b"pre-device=lavender\n#" + b"x" * (2 * package.READ_CHUNK))
    artifact_manifest(path)
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    original = package._Reader.read
    def read(reader, size=-1):
        if size == package.READ_CHUNK:
            assert callable(reader.cancelled)
            entered.set()
            release.wait(4)
            try:
                return original(reader, size)
            except VerificationCancelled:
                stopped.set()
                raise
        return original(reader, size)
    monkeypatch.setattr(package._Reader, "read", read)
    monkeypatch.setattr("curseofdroid.gui.installation.validate", lambda *a, **kw: pytest.fail("metadata cancellation reached hashing"))
    preview.setPath("main", str(path))
    preview.verify()
    wait(app, entered.is_set)
    try:
        preview.cancel()
    finally:
        release.set()
        wait(app, lambda: not preview.busy)
    assert stopped.is_set() and preview.state == "cancelled" and not preview.planText and not preview.files
