from __future__ import annotations

import datetime as dt
import re
import urllib.error
from dataclasses import dataclass, field
from typing import Literal

from ..platform.net import Fetcher, NotFound, fetch_text

Kind = Literal["rom", "recovery", "gsi"]


@dataclass
class Artifact:
    filename: str
    url: str
    size: int | None = None
    hashes: dict[str, str] = field(default_factory=dict)  # {"sha256": ..., "md5": ...}
    headers: dict[str, str] = field(default_factory=dict)  # e.g. TWRP needs a Referer


@dataclass
class Build:
    project: str
    kind: Kind
    codename: str
    version: str
    date: dt.date | None
    artifacts: list[Artifact]  # first one is the main package (ROM zip / recovery image)
    android: str = ""
    variant: str = ""  # e.g. "vanilla", "gapps", "kernel_419", "nightly"
    device_name: str = ""
    info_url: str = ""  # install instructions / forum thread
    notes: str = ""

    @property
    def main(self) -> Artifact:
        return self.artifacts[0]


def hashes_from(sha256: str | None = None, md5: str | None = None, unknown: str | None = None) -> dict[str, str]:
    """Some projects put an md5 in a field called sha256 (and vice versa): classify by length."""
    out: dict[str, str] = {}
    for value in (sha256, md5, unknown):
        if not value or not re.fullmatch(r"[0-9a-fA-F]+", value):
            continue
        algo = {64: "sha256", 32: "md5", 40: "sha1"}.get(len(value))
        if algo:
            out.setdefault(algo, value.lower())
    return out


def from_timestamp(ts) -> dt.date | None:
    try:
        return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).date()
    except (TypeError, ValueError, OverflowError):
        return None


class Provider:
    name = ""
    kind: Kind = "rom"
    homepage = ""

    def __init__(self, fetch: Fetcher = fetch_text):
        self.fetch = fetch

    def builds(self, codename: str) -> list[Build]:
        raise NotImplementedError

    def _json(self, url: str):
        import json
        return json.loads(self.fetch(url))

    def _try(self, url: str):
        """JSON or None when the project doesn't know the device (404; LineageOS answers 400)."""
        try:
            return self._json(url)
        except NotFound:
            return None
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return None
            raise
