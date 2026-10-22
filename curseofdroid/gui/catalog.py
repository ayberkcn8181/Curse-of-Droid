"""Read-only, cancellable QML catalog projection over the existing provider registry."""
from __future__ import annotations

import datetime as dt
import copy
import ipaddress
import itertools
import queue
import re
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from ..catalog.base import Build
from ..catalog.providers import ALL_PROVIDERS, ENDED, find_builds, is_stale
from ..platform.net import fetch_text
from .workers import Job, start

_CODENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_HASH_LENGTHS = {"sha256": 64, "sha1": 40, "md5": 32}


def https_link(value) -> str:
    """Only explicitly chosen HTTPS links; no credentials, local schemes or literal local addresses."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) <= 32 for c in value) or "\\" in value:
        return ""
    try:
        p = urlsplit(value)
        if p.scheme.lower() != "https" or not p.hostname or p.username or p.password:
            return ""
        if p.port is not None and not 1 <= p.port <= 65535:
            return ""
        host = p.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
    except ValueError:
        return ""
    return value


def _text(value):
    return str(value or "")[:2000]


def build_row(build: Build, homepage: str, identifier: int) -> dict:
    artifact = build.main
    hashes = {key: value.lower() for key, value in artifact.hashes.items()
              if key in _HASH_LENGTHS and isinstance(value, str)
              and re.fullmatch(r"[0-9a-fA-F]{%d}" % _HASH_LENGTHS[key], value)}
    artifacts = [dict(filename=_text(a.filename), size=str(a.size) if a.size is not None else "")
                 for a in build.artifacts]
    date = build.date.isoformat() if isinstance(build.date, dt.date) else ""
    return dict(id=identifier, project=_text(build.project), kind=build.kind,
                codename=_text(build.codename), version=_text(build.version), android=_text(build.android),
                date=date, age="unknown" if not date else ("future" if build.date > dt.date.today() else ("old" if is_stale(build) else "recent")),
                variant=_text(build.variant), deviceName=_text(build.device_name), notes=_text(build.notes),
                ended=ENDED in build.notes, filename=_text(artifact.filename), direct=bool(artifact.direct),
                size=str(artifact.size) if artifact.size is not None else "", hashes=hashes,
                hashKinds=", ".join(key.upper() for key in sorted(hashes)),
                sourceUrl=https_link(artifact.url), instructionsUrl=https_link(build.info_url),
                homepageUrl=https_link(homepage), artifacts=artifacts)


class _Cancelled(Exception):
    pass


class Catalog(QObject):
    changed = Signal()
    notice = Signal(str)
    operationReported = Signal(str)
    downloadRequested = Signal(object)

    def __init__(self, kind, dashboard, providers=None, fetch=None, parent=None):
        # Native ownership outlives queued worker callbacks even if a Python caller drops its reference.
        super().__init__(parent if parent is not None else dashboard)
        if kind not in ("rom", "recovery"):
            raise ValueError("unknown catalog kind")
        self.kind = kind
        self.dashboard = dashboard
        registry = list(ALL_PROVIDERS if providers is None else providers)
        # Only explicitly named recovery.img artifacts are projected as LineageOS Recovery.
        # boot/vendor_boot/init_boot images remain related ROM artifacts, not guessed recovery methods.
        self._providers = [p for p in registry if p.kind == kind or (kind == "recovery" and p.name == "LineageOS")]
        self._fetch = fetch if fetch is not None else fetch_text
        self._identifiers = itertools.count()
        self._rows = []
        self._visible = []
        self._by_id = {}
        self._sources = {}
        self._selected = -1
        self._busy = False
        self._state = "idle"
        self._query = ""
        self._filter = ""
        self._project = ""
        self._android = ""
        self._age = ""
        self._sort = "newest"
        self._errors = []
        self._done_count = 0
        self._cancel = threading.Event()
        self._pending = queue.SimpleQueue()
        self._device_key = None
        self._invalidated = False
        self._job = None
        dashboard.changed.connect(self._device_changed)

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(str, notify=changed)
    def query(self):
        return self._query

    @Property("QVariantList", notify=changed)
    def rows(self):
        return self._visible

    @Property("QVariantList", notify=changed)
    def errors(self):
        return self._errors

    @Property(int, notify=changed)
    def totalCount(self):
        return len(self._rows)

    @Property(int, notify=changed)
    def completedProviders(self):
        return self._done_count

    @Property(int, constant=True)
    def providerCount(self):
        return len(self._providers)

    @Property("QStringList", constant=True)
    def projects(self):
        return sorted({"LineageOS Recovery" if self.kind == "recovery" and p.name == "LineageOS" else p.name
                       for p in self._providers})

    @Property("QStringList", notify=changed)
    def androidVersions(self):
        return sorted({r["android"] for r in self._rows if r["android"]},
                      key=lambda v: [int(x) for x in re.findall(r"\d+", v)], reverse=True)

    @Property("QVariantMap", notify=changed)
    def selected(self):
        return self._by_id.get(self._selected, {})

    def _identity(self):
        d = self.dashboard.selected_device()
        return (d.serial, tuple(d.profile.codenames)) if d and d.profile else None

    @Slot()
    def _device_changed(self):
        if self._device_key is not None and self._device_key != self._identity():
            self._invalidated = True
            self._cancel.set()
            self._rows, self._visible, self._by_id, self._sources, self._errors = [], [], {}, {}, []
            self._selected = -1
            self._state = "invalidated"
            self._device_key = None
            self.changed.emit()

    @Slot(str)
    def search(self, codename):
        self._search([codename.strip()], None)

    @Slot()
    def searchSelected(self):
        identity = self._identity()
        if identity is None:
            self.notice.emit(self.tr("Select an identified device with a known codename first."))
            return
        self._search(list(identity[1]), identity)

    def _search(self, names, identity):
        if self._busy:
            return
        if not names or len(names) > 16 or any(not _CODENAME.fullmatch(c) for c in names):
            self.notice.emit(self.tr("Enter a device codename using letters, digits, dots, underscores or hyphens (1–64 characters)."))
            return
        names = list(dict.fromkeys(names))
        self._device_key = identity
        self._invalidated = False
        self._cancel = threading.Event()
        self._pending = queue.SimpleQueue()
        self._query = ", ".join(names)
        self._rows, self._visible, self._by_id, self._sources, self._errors = [], [], {}, {}, []
        self._selected = -1
        self._done_count = 0
        self._busy = True
        self._state = "searching"
        # A fresh query resets filters so a prior device's Android version does not hide new results.
        self._filter, self._project, self._android, self._age = "", "", "", ""
        cancel, pending, providers, fetch, kind = self._cancel, self._pending, self._providers, self._fetch, self.kind
        identifiers = self._identifiers

        def checked_fetch(url):
            if cancel.is_set():
                raise _Cancelled()
            result = fetch(url)
            if cancel.is_set():
                raise _Cancelled()
            return result

        def work(progress):
            for completed, provider in enumerate(providers, 1):
                if cancel.is_set():
                    break
                result, errors = find_builds(names, providers=[provider], fetch=checked_fetch)
                if cancel.is_set():
                    break
                batch = []
                for builds in result.values():
                    for build in builds:
                        try:
                            if kind == "recovery" and provider.name == "LineageOS":
                                images = [a for a in build.artifacts if a.filename == "recovery.img"]
                                builds_to_show = [Build("LineageOS Recovery", "recovery", build.codename,
                                    build.version, build.date, [a], android=build.android, info_url=build.info_url,
                                    notes="Published recovery.img; installation partition/method must be checked in device instructions.") for a in images]
                            else:
                                builds_to_show = [build]
                            for b in builds_to_show:
                                row = build_row(b, provider.homepage, next(identifiers))
                                row["_source"] = copy.deepcopy(b)
                                batch.append(row)
                        except (AttributeError, TypeError, ValueError, IndexError):
                            errors.append(f"{provider.name}: malformed build metadata skipped")
                pending.put((batch, [_text(e)[:500] for e in errors]))
                progress(completed, len(providers))
            return cancel.is_set()

        self._job = Job(work, on_done=self._finished, on_failed=self._failed, on_progress=self._progress)
        self.changed.emit()
        self.operationReported.emit(self.tr("Catalog search started for ") + self._query)
        start(self._job)

    def _drain(self):
        while not self._pending.empty():
            batch, errors = self._pending.get()
            if not self._invalidated:
                for row in batch:
                    self._sources[row["id"]] = row.pop("_source")
                self._rows.extend(batch)
                self._errors.extend(errors)
        self._by_id = {r["id"]: r for r in self._rows}
        self._apply_filters()

    @Slot(int, int)
    def _progress(self, completed, total):
        self._done_count = completed
        self._drain()
        self.changed.emit()

    @Slot(object)
    def _finished(self, cancelled):
        self._drain()
        self._busy, self._job = False, None
        if self._invalidated:
            self._state = "invalidated"
        elif cancelled:
            self._state = "cancelled"
        elif self._errors:
            self._state = "partial" if self._rows else "error"
        else:
            self._state = "ready" if self._rows else "empty"
        self.changed.emit()
        self.operationReported.emit(self.tr("Catalog search finished: ") + self._state)

    @Slot(str)
    def _failed(self, message):
        self._busy, self._job = False, None
        self._state = "error"
        self._errors.append(self.tr("Catalog operation failed. Check network access and provider metadata."))
        self.changed.emit()

    @Slot()
    def cancel(self):
        if self._busy:
            self._cancel.set()
            self._state = "cancelling"
            self.changed.emit()

    @Slot(str, str, str, str, str)
    def setFilters(self, text, project, android, age, sort):
        if project and project not in self.projects:
            return
        if age not in ("", "recent", "old", "unknown", "future") or sort not in ("newest", "oldest", "project"):
            return
        self._filter, self._project, self._android, self._age, self._sort = text[:200], project, android, age, sort
        self._apply_filters()
        self.changed.emit()

    def _apply_filters(self):
        needle = self._filter.casefold()
        self._visible = [r for r in self._rows if (not self._project or r["project"] == self._project)
            and (not self._android or r["android"] == self._android) and (not self._age or r["age"] == self._age)
            and (not needle or needle in " ".join(r[k] for k in ("project", "version", "variant", "filename", "notes")).casefold())]
        if self._sort == "project":
            self._visible.sort(key=lambda r: (r["project"].casefold(), r["date"]), reverse=False)
        else:
            self._visible.sort(key=lambda r: (bool(r["date"]), r["date"] if self._sort == "newest" else ""), reverse=True)
            if self._sort == "oldest":
                self._visible.sort(key=lambda r: (not bool(r["date"]), r["date"]))
        if not any(r["id"] == self._selected for r in self._visible):
            self._selected = -1

    @Slot(int)
    def select(self, identifier):
        self._selected = identifier if any(r["id"] == identifier for r in self._visible) else -1
        self.changed.emit()

    @Slot()
    def queueSelected(self):
        if self._selected in self._sources and self.selected:
            self.downloadRequested.emit(copy.deepcopy(self._sources[self._selected]))
        else:
            self.notice.emit(self.tr("Select a current catalog result first."))

    @Slot(str)
    def openSelectedLink(self, role):
        key = {"source": "sourceUrl", "instructions": "instructionsUrl", "project": "homepageUrl"}.get(role)
        if key and (url := https_link(self.selected.get(key))):
            if not QDesktopServices.openUrl(QUrl(url)):
                self.notice.emit(self.tr("Could not open the link in your browser."))
        else:
            self.notice.emit(self.tr("No permitted HTTPS link is available for this selection."))
