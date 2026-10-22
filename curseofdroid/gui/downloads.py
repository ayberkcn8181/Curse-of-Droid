"""Persistent, single-worker download queue over the shared network backend. Never installs files."""
from __future__ import annotations

import copy
import json
import queue
import re
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ..catalog.base import Artifact, Build
from ..catalog.providers import TWRP
from ..platform.net import DownloadCancelled, VerificationError, _verification_inputs, download, download_destination, verification_label, verify
from ..platform.paths import data_dir, downloads_dir
from .catalog import https_link
from .workers import Job, start


def _source(build):
    if not isinstance(build, Build) or build.kind not in ("rom", "recovery", "gsi") or not build.main.direct or not https_link(build.main.url):
        raise ValueError("Choose a direct HTTPS artifact from a catalog result.")
    artifact = build.main
    _verification_inputs(artifact.size, artifact.hashes)
    download_destination(Path("."), build.codename, artifact.filename)
    # Current providers need only a public Referer. Do not persist credentials in queue history.
    if any(k.lower() != "referer" or not https_link(v) for k, v in artifact.headers.items()):
        raise ValueError("This artifact needs unsupported private request headers.")
    return dict(project=str(build.project)[:100], kind=build.kind, codename=build.codename,
                filename=artifact.filename, url=artifact.url, size=artifact.size,
                hashes=dict(artifact.hashes), headers=dict(artifact.headers))


def _build(source):
    return Build(source["project"], source["kind"], source["codename"], "", None,
                 [Artifact(source["filename"], source["url"], source["size"], source["hashes"], source["headers"])])


class DownloadManager(QObject):
    changed = Signal()
    notice = Signal(str)
    added = Signal()
    operationReported = Signal(str)

    def __init__(self, parent=None, root=None, manifest=None):
        super().__init__(parent if parent is not None else QCoreApplication.instance())
        self.root = Path(root) if root is not None else downloads_dir()
        self.manifest = Path(manifest) if manifest is not None else data_dir() / "download-queue.json"
        self._items = []
        self._active = ""
        self._job = None
        self._cancel = threading.Event()
        self._pending = queue.SimpleQueue()
        self._storage_error = ""
        self._load_failed = False
        self._write_locked = False
        self._closed = False
        self._load()
        self._lock = QLockFile(str(self.manifest) + ".lock")
        self._lock.setStaleLockTime(0)
        try:
            self.manifest.parent.mkdir(parents=True, exist_ok=True)
            if not self._lock.tryLock(0):
                self._write_locked = True
                self._storage_error = "Download history is read-only. Close the other application instance and reopen this one."
        except OSError:
            self._write_locked = True
            self._storage_error = "Download history is unavailable. Check application data directory permissions."

    @Property(bool, notify=changed)
    def busy(self):
        return bool(self._active)

    @Property(str, notify=changed)
    def storageError(self):
        return self._storage_error

    @Property(int, notify=changed)
    def completedCount(self):
        return sum(i["state"] == "complete" for i in self._items)

    @Property("QVariantList", notify=changed)
    def rows(self):
        result = []
        for item in reversed(self._items):
            s = item["source"]
            result.append(dict(id=item["id"], project=s["project"], filename=s["filename"], codename=s["codename"],
                state=item["state"], done=str(item["done"]), total=str(item["total"] or ""),
                fraction=min(1, item["done"] / item["total"]) if item["total"] else 0,
                integrity=item["integrity"], error=item["error"], hashes=", ".join(sorted(s["hashes"])),
                canCheck=bool(s["hashes"] or s["size"] is not None), active=item["id"] == self._active))
        return result

    def _path(self, item):
        s = item["source"]
        directory = self.root / item["id"]
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.root.resolve()):
            raise VerificationError("Download folder escapes the application downloads directory")
        return download_destination(directory, s["codename"], s["filename"])

    def _load(self):
        if not self.manifest.exists():
            return
        try:
            if self.manifest.stat().st_size > 2 << 20:
                raise ValueError("queue too large")
            document = json.loads(self.manifest.read_text(encoding="utf-8"))
            if document["version"] != 1 or not isinstance(document["items"], list) or len(document["items"]) > 50:
                raise ValueError("unsupported queue")
            for saved in document["items"]:
                identifier = saved["id"]
                if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
                    raise ValueError("invalid queue identity")
                if any(i["id"] == identifier for i in self._items):
                    raise ValueError("duplicate queue identity")
                source = _source(_build(saved["source"]))
                item = dict(id=identifier, source=source, state="paused", done=0, total=source["size"] or 0,
                            integrity="Not checked in this session", error="", mode=saved.get("mode", "download"))
                if item["mode"] not in ("download", "verify"):
                    raise ValueError("invalid task")
                path = self._path(item)
                if saved["state"] in ("complete", "needs-check", "missing"):
                    item["state"] = "needs-check" if path.is_file() else "missing"
                elif saved["state"] == "failed":
                    item["state"] = "failed"
                part = path.with_name(path.name + ".part")
                item["done"] = part.stat().st_size if part.is_file() else 0
                self._items.append(item)
        except (OSError, ValueError, VerificationError, TypeError, KeyError, IndexError, AttributeError):
            self._items = []
            self._load_failed = True
            self._storage_error = "Saved queue could not be read. Preserve and repair download-queue.json before adding files."

    def _save(self):
        if self._load_failed or self._write_locked or self._closed:
            return False
        try:
            self.manifest.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.manifest.with_suffix(".tmp")
            if self.manifest.is_symlink() or temporary.is_symlink():
                raise OSError("queue symlink")
            temporary.write_text(json.dumps(dict(version=1, items=self._items), indent=2), encoding="utf-8")
            temporary.replace(self.manifest)
            self._storage_error = ""
            return True
        except OSError:
            self._storage_error = "Could not save download history. Check the application data directory permissions."
            self.notice.emit(self._storage_error)
            return False

    def enqueue(self, build):
        """Python-only entry point: Runtime wires a selected catalog Build, never a QML-supplied URL."""
        try:
            if self._load_failed or self._write_locked or self._closed:
                raise ValueError(self._storage_error)
            source = _source(copy.deepcopy(build))
            if any(all(i["source"][k] == value for k, value in source.items() if k != "hashes")
                   and (not source["hashes"] or i["source"]["hashes"] == source["hashes"]) for i in self._items):
                self.notice.emit(self.tr("This artifact is already in download history."))
                self.added.emit()
                return
            if len(self._items) >= 50:
                raise ValueError("Download history is limited to 50 records. Remove an inactive record first.")
            item = dict(id=uuid.uuid4().hex, source=source, state="queued", done=0,
                        total=source["size"] or 0, integrity="Not checked", error="", mode="download")
            self._path(item)
            self._items.append(item)
            if not self._save():
                item["state"] = "paused"
            self.changed.emit()
            self.added.emit()
            self._advance()
        except (ValueError, VerificationError, OSError, TypeError, AttributeError, IndexError) as error:
            self.notice.emit(str(error)[:300])

    def _advance(self):
        if self.busy:
            return
        item = next((i for i in self._items if i["state"] == "queued"), None)
        if item is None or not self._save():
            return
        try:
            path = self._path(item)
        except (VerificationError, OSError):
            item["state"], item["error"] = "failed", "Download destination is unavailable or unsafe."
            self._save()
            self.changed.emit()
            return
        self._active = item["id"]
        self._cancel, self._pending = threading.Event(), queue.SimpleQueue()
        cancel, pending = self._cancel, self._pending
        source, mode = copy.deepcopy(item["source"]), item["mode"]
        item["state"] = "verifying" if mode == "verify" else "downloading"
        item["error"] = ""
        self.changed.emit()
        self.operationReported.emit(self.tr("File operation started: ") + source["filename"])

        def work(progress):
            last = 0

            def update(done, total):
                nonlocal last
                now = time.monotonic()
                if now - last > .1 or done == total:
                    pending.put(("bytes", (done, total or 0)))
                    progress(0, 0)  # Real byte counters stay in Python, outside Qt's 32-bit int signal.
                    last = now

            def phase(state):
                pending.put(("state", state))
                progress(0, 0)

            try:
                if mode == "verify":
                    verify(path, size=source["size"], hashes=source["hashes"], cancelled=cancel.is_set)
                else:
                    if source["project"] == "TWRP" and not source["hashes"]:
                        phase("checksums")
                        build = _build(source)
                        TWRP().fill_hash(build)
                        source["hashes"] = build.main.hashes
                        pending.put(("hashes", source["hashes"]))
                    download(source["url"], path, size=source["size"], hashes=source["hashes"],
                             headers=source["headers"], progress=update, cancelled=cancel.is_set, phase=phase)
                return dict(state="complete", size=path.stat().st_size, error="", hashes=source["hashes"])
            except DownloadCancelled:
                return dict(state="paused", error="", hashes=source["hashes"])
            except VerificationError as error:
                return dict(state="failed", error=str(error)[:300], hashes=source["hashes"])
            except Exception as error:
                # URLs, tokens and transport tracebacks must not enter QML or persistent history.
                return dict(state="failed", error=f"File/network operation failed ({type(error).__name__}). Retry when available.", hashes=source["hashes"])

        self._job = Job(work, on_done=self._finished, on_failed=self._failed, on_progress=self._progress)
        start(self._job)

    def close(self):
        """Release the history writer lock only after the last operation has finished."""
        if self.busy:
            return False
        if self._lock.isLocked():
            self._lock.unlock()
        self._closed = True
        return True

    @Slot(int, int)
    def _progress(self, *_):
        item = next((i for i in self._items if i["id"] == self._active), None)
        if item is None:
            return
        while not self._pending.empty():
            kind, value = self._pending.get()
            if kind == "bytes":
                item["done"], item["total"] = value
            elif kind == "state" and item["state"] != "pausing":
                item["state"] = value
            elif kind == "hashes":
                item["source"]["hashes"] = value
        self.changed.emit()

    @Slot(object)
    def _finished(self, result):
        self._progress()
        item = next(i for i in self._items if i["id"] == self._active)
        item["state"], item["error"] = result["state"], result["error"]
        item["source"]["hashes"] = result["hashes"]
        if result["state"] == "complete":
            item["done"] = item["total"] = result["size"]
            item["integrity"] = verification_label(size=item["source"]["size"], hashes=result["hashes"])
        self._active, self._job = "", None
        self._save()
        self.changed.emit()
        self.operationReported.emit(self.tr("File operation finished: ") + item["state"])
        self._advance()

    @Slot(str)
    def _failed(self, _message):
        item = next(i for i in self._items if i["id"] == self._active)
        self._finished(dict(state="failed", error="Download worker failed. Retry the operation.", hashes=item["source"]["hashes"]))

    @Slot(str)
    def pause(self, identifier):
        item = next((i for i in self._items if i["id"] == identifier), None)
        if item and identifier == self._active:
            item["state"] = "pausing"
            self._cancel.set()
        elif item and item["state"] == "queued":
            item["state"] = "paused"
        self._save()
        self.changed.emit()

    @Slot()
    def pauseAll(self):
        for item in self._items:
            if item["id"] == self._active:
                item["state"] = "pausing"
                self._cancel.set()
            elif item["state"] == "queued":
                item["state"] = "paused"
        self._save()
        self.changed.emit()

    @Slot(str)
    def resume(self, identifier):
        item = next((i for i in self._items if i["id"] == identifier), None)
        if item and item["state"] in ("paused", "failed", "missing"):
            if item["state"] in ("failed", "missing"):
                item["mode"] = "download"
            item["state"], item["error"] = "queued", ""
            self._save()
            self.changed.emit()
            self._advance()

    @Slot(str)
    def recheck(self, identifier):
        item = next((i for i in self._items if i["id"] == identifier), None)
        if item and identifier != self._active and item["state"] in ("complete", "needs-check"):
            item["state"], item["mode"], item["integrity"] = "queued", "verify", "Not checked"
            self._save()
            self.changed.emit()
            self._advance()

    @Slot(str)
    def remove(self, identifier):
        if identifier != self._active:
            self._items = [i for i in self._items if i["id"] != identifier]
            self._save()
            self.changed.emit()

    @Slot(str)
    def openFolder(self, identifier):
        item = next((i for i in self._items if i["id"] == identifier), None)
        if item and item["state"] in ("complete", "needs-check"):
            try:
                folder = self._path(item).parent
                if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve()))):
                    self.notice.emit(self.tr("Could not open the download folder."))
            except (OSError, VerificationError):
                self.notice.emit(self.tr("The download folder is unavailable."))
