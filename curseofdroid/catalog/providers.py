"""Official build sources. Endpoints checked against the live services on 2026-10-12."""

from __future__ import annotations

import datetime as dt
import html
import re

from ..platform.net import NotFound
from .base import Artifact, Build, Provider, from_timestamp, hashes_from

RAW = "https://raw.githubusercontent.com"


def _num(v: str) -> float:
    m = re.match(r"(\d+(?:\.\d+)?)", v)
    return float(m.group(1)) if m else 0.0


# LineageOS version -> Android version (only releases whose mapping is documented)
_LINEAGE_ANDROID = {"17": "10", "18": "11", "19": "12", "20": "13", "21": "14", "22": "15", "23": "16"}


class LineageOS(Provider):
    name = "LineageOS"
    homepage = "https://lineageos.org"
    API = "https://download.lineageos.org/api/v2/devices/{c}"

    def builds(self, codename):
        info = self._try(self.API.format(c=codename))
        if not info:
            return []
        out = []
        for b in self._try(self.API.format(c=codename) + "/builds") or []:
            files = b.get("files", [])
            files.sort(key=lambda f: not f["filename"].endswith(".zip"))  # ROM zip first, then boot/recovery imgs
            arts = [Artifact(f["filename"], f["url"], f.get("size"), hashes_from(sha256=f.get("sha256")))
                    for f in files]
            if arts:
                out.append(Build(self.name, "rom", codename, b.get("version", ""), from_timestamp(b.get("datetime")),
                                 arts, android=_LINEAGE_ANDROID.get(b.get("version", "").split(".")[0], ""),
                                 variant=b.get("type", ""), device_name=info.get("name", ""),
                                 info_url=info.get("info_url", "")))
        return out


class _OtaJson(Provider):
    """crDroid / Evolution X / DerpFest style: {"response": [{filename, download|url, sha256|id, ...}]}."""

    def _parse(self, data, codename, android=""):
        out = []
        for r in (data or {}).get("response", []):
            url = r.get("download") or r.get("url")
            if not url:
                continue
            arts = [Artifact(r["filename"], url, r.get("size"),
                             hashes_from(sha256=r.get("sha256"), md5=r.get("md5"), unknown=r.get("id")))]
            out.append(Build(self.name, "rom", codename, str(r.get("version", "")),
                             from_timestamp(r.get("timestamp") or r.get("datetime")), arts, android=android,
                             variant=r.get("buildtype") or r.get("romtype") or "",
                             device_name=" ".join(x for x in (r.get("oem"), r.get("device")) if x),
                             info_url=r.get("forum") or r.get("website") or "",
                             notes="not maintained anymore" if r.get("currently_maintained") is False else ""))
        return out


class CrDroid(_OtaJson):
    name = "crDroid"
    homepage = "https://crdroid.net"
    REPO = "crdroidandroid/android_vendor_crDroidOTA"

    def branches(self) -> list[str]:
        try:
            data = self._json(f"https://api.github.com/repos/{self.REPO}/branches?per_page=100")
            names = [b["name"] for b in data if re.fullmatch(r"\d+\.\d+", b["name"])]
        except Exception:  # API rate limit etc.: known branches
            names = ["17.0", "16.0", "15.0", "14.0", "13.0"]
        return sorted(names, key=_num, reverse=True)

    def builds(self, codename):
        for branch in self.branches():  # newest Android version that has the device
            data = self._try(f"{RAW}/{self.REPO}/{branch}/{codename}.json")
            if data:
                return self._parse(data, codename, android=branch.split(".")[0])
        return []


class EvolutionX(_OtaJson):
    """One OTA branch per Android version (udc=14, vic=15, bka=16, cnb=17), each with a "-vanilla" twin
    (no Google apps). New branches start with few devices, so the newest branch that has the device wins."""
    name = "Evolution X"
    homepage = "https://evolution-x.org"
    REPO = "Evolution-X/OTA"
    ANDROID = {"udc": "14", "vic": "15", "bka": "16", "cnb": "17"}

    def branches(self) -> list[str]:
        try:
            data = self._json(f"https://api.github.com/repos/{self.REPO}/branches?per_page=100")
            names = [b["name"] for b in data if not b["name"].endswith("-vanilla")]
        except Exception:  # API rate limit etc.
            names = list(self.ANDROID)
        known = [n for n in self.ANDROID if n in names]  # oldest -> newest
        return list(reversed(known)) + [n for n in names if n not in self.ANDROID]

    def builds(self, codename):
        for branch in self.branches():
            gapps = self._try(f"{RAW}/{self.REPO}/{branch}/builds/{codename}.json")
            if not gapps:
                continue
            android = self.ANDROID.get(branch, "")
            out = self._parse(gapps, codename, android)
            for b in out:
                b.variant = "with Google apps"
            vanilla = self._parse(self._try(f"{RAW}/{self.REPO}/{branch}-vanilla/builds/{codename}.json"),
                                  codename, android)
            for b in vanilla:
                b.variant = "vanilla (no Google apps)"
            return out + vanilla
        return []


class DerpFest(_OtaJson):
    name = "DerpFest"
    homepage = "https://derpfest.org"

    def builds(self, codename):
        return self._parse(self._try(f"{RAW}/DerpFest-AOSP/Updater-Stuff/master/{codename}.json"), codename)


class PixelOS(Provider):
    name = "PixelOS"
    homepage = "https://pixelos.net"
    BASE = f"{RAW}/PixelOS-AOSP/official_devices/seventeen/API"

    def builds(self, codename):
        data = self._try(f"{self.BASE}/updater/{codename}.json")
        out = []
        for b in data or []:
            for f in b.get("files", []):
                arts = [Artifact(f["filename"], f["url"], f.get("size"), hashes_from(unknown=f.get("sha256")))]
                out.append(Build(self.name, "rom", codename, str(b.get("version", "")),
                                 from_timestamp(b.get("datetime")), arts, variant=b.get("type", ""),
                                 android=str(b.get("version", "")).split(".")[0]))
        return out


class TWRP(Provider):
    name = "TWRP"
    kind = "recovery"
    homepage = "https://twrp.me"
    BASE = "https://dl.twrp.me/{c}/"
    _FILE = re.compile(r'href="/(?P<c>[^/"]+)/(?P<f>twrp-[^"/]+?\.img)\.html"')

    def builds(self, codename):
        try:
            page = self.fetch(self.BASE.format(c=codename))
        except NotFound:
            return []
        files = []
        for m in self._FILE.finditer(page):
            f = html.unescape(m["f"])
            if f not in files:
                files.append(f)
        out = []
        for f in files:
            v = re.match(r"twrp-([\d.]+(?:_\d+)?-\d+)", f)
            url = self.BASE.format(c=codename) + f
            # dl.twrp.me only serves the image with the download page as referer
            out.append(Build(self.name, "recovery", codename, v.group(1) if v else "", None,
                             [Artifact(f, url, headers={"Referer": url + ".html"})],
                             info_url=f"https://twrp.me/Devices/"))
        out.sort(key=lambda b: [int(x) for x in re.findall(r"\d+", b.version)], reverse=True)
        return out

    def fill_hash(self, build: Build) -> None:
        """TWRP publishes <file>.sha256 next to each image; fetched only for the build that will be used."""
        try:
            text = self.fetch(build.main.url + ".sha256")
            build.main.hashes.update(hashes_from(sha256=text.split()[0]))
        except (NotFound, IndexError):
            pass


class OrangeFox(Provider):
    name = "OrangeFox"
    kind = "recovery"
    homepage = "https://orangefox.download"
    API = "https://api.orangefox.download/v3"

    def builds(self, codename):
        data = self._try(f"{self.API}/releases/?codename={codename}&type=stable&sort=date_desc&limit=10")
        out = []
        for r in (data or {}).get("data", []):
            url = (r.get("mirrors") or {}).get("DL") or f"https://dl.orangefox.download/{r['_id']}"
            out.append(Build(self.name, "recovery", codename, r.get("version", ""), from_timestamp(r.get("date")),
                             [Artifact(r["filename"], url, r.get("size"), hashes_from(md5=r.get("md5")))],
                             variant=r.get("variant", ""), info_url=f"https://orangefox.download/device/{r.get('device_id', '')}"))
        return out


class ParanoidAndroid(Provider):
    name = "Paranoid Android"
    homepage = "https://paranoidandroid.co"

    def builds(self, codename):
        data = self._try(f"https://api.paranoidandroid.co/updates/{codename}")
        out = []
        for u in (data or {}).get("updates", []):
            size = int(u["size"]) if str(u.get("size", "")).isdigit() else None
            arts = [Artifact(u["filename"], u["url"], size, hashes_from(sha256=u.get("recovery_sha256")))]
            if u.get("fastboot"):  # fastboot image package, for devices whose instructions use it
                arts.append(Artifact(u["fastboot"].rsplit("/", 1)[-1], u["fastboot"], None,
                                     hashes_from(sha256=u.get("fastboot_sha256"))))
            out.append(Build(self.name, "rom", codename, f"{u.get('version', '')} {u.get('version_code', '')}".strip(),
                             from_timestamp(u.get("datetime")), arts, android=str(u.get("android_version", "")),
                             variant=u.get("build_type", ""), info_url=f"{self.homepage}/{codename}"))
        out.sort(key=lambda b: b.date or dt.date.min, reverse=True)
        return out


class RisingOS(_OtaJson):
    name = "RisingOS"
    homepage = "https://risingosrevived.tech"
    BASE = f"{RAW}/RisingOS-Revived/official_devices/fifteen/OTA/device"

    def builds(self, codename):
        out = []
        for flavour, label in (("GAPPS", "with Google apps"), ("CORE", "vanilla (no Google apps)"),
                               ("MICROG", "with microG")):
            for b in self._parse(self._try(f"{self.BASE}/{flavour}/{codename}.json"), codename):
                b.variant = label
                out.append(b)
        return out


class InfinityX(_OtaJson):
    name = "Project Infinity-X"
    homepage = "https://projectinfinity-x.com"
    REPO = "ProjectInfinity-X/official_devices"

    def builds(self, codename):
        for android in ("17", "16", "15", "14"):
            out = []
            for flavour, label in (("gapps", "with Google apps"), ("vanilla", "vanilla (no Google apps)")):
                for b in self._parse(self._try(f"{RAW}/{self.REPO}/{android}/{flavour}/{codename}.json"),
                                     codename, android):
                    b.variant = label
                    out.append(b)
            if out:
                return out
        return []


class AxionOS(_OtaJson):
    name = "AxionOS"
    homepage = "https://axionos.org"
    BASE = f"{RAW}/AxionAOSP/official_devices/main/OTA"

    def builds(self, codename):
        out = []
        for flavour, label in (("GMS", "with Google apps"), ("VANILLA", "vanilla (no Google apps)")):
            for b in self._parse(self._try(f"{self.BASE}/{flavour}/{codename}.json"), codename):
                b.variant = label
                out.append(b)
        return out


class VoltageOS(_OtaJson):
    name = "VoltageOS"
    homepage = "https://voltageos.com"
    REPO = "VoltageOS/android_vendor_voltageota"

    def builds(self, codename):
        for android in ("17", "16", "15", "14"):
            # old device files are carried over into newer branches, so the branch isn't the Android version
            if data := self._try(f"{RAW}/{self.REPO}/{android}/{codename}.json"):
                return self._parse(data, codename)
        return []


class YAAP(_OtaJson):
    name = "YAAP"
    homepage = "https://yaap.github.io"

    def builds(self, codename):
        return self._parse(self._try(f"{RAW}/yaap/ota-info/full-signed/{codename}/{codename}.json"), codename)


class GrapheneOS(Provider):
    """Pixels only. GrapheneOS is installed with its own web installer (or CLI) from factory images, not through a
    custom recovery; the build is listed so the user sees it, with the official install guide."""
    name = "GrapheneOS"
    homepage = "https://grapheneos.org"

    def builds(self, codename):
        try:
            text = self.fetch(f"https://releases.grapheneos.org/{codename}-stable")
        except NotFound:
            return []
        parts = text.split()
        if len(parts) < 2 or not parts[0].isdigit():
            return []
        version, ts = parts[0], parts[1]
        url = f"https://releases.grapheneos.org/{codename}-install-{version}.zip"
        return [Build(self.name, "rom", codename, version, from_timestamp(ts), [Artifact(url.rsplit("/", 1)[-1], url)],
                      variant="factory images", info_url="https://grapheneos.org/install/web",
                      notes="installed with GrapheneOS's own web installer, not through a custom recovery")]


ALL_PROVIDERS = [LineageOS, CrDroid, EvolutionX, PixelOS, DerpFest, ParanoidAndroid, RisingOS, InfinityX,
                 AxionOS, VoltageOS, YAAP, GrapheneOS, TWRP, OrangeFox]


def find_builds(codenames: list[str], providers=None, fetch=None) -> tuple[dict[str, list[Build]], list[str]]:
    """Ask every provider about every codename alias; first alias with results wins per provider.

    Returns (builds per project, errors); one broken source must not hide the others."""
    results: dict[str, list[Build]] = {}
    errors: list[str] = []
    for cls in providers or ALL_PROVIDERS:
        p = cls(fetch) if fetch else cls()
        for c in codenames:
            try:
                found = p.builds(c)
            except Exception as e:
                found = []
                errors.append(f"{p.name} ({c}): {e}")
            if found:
                results[p.name] = found
                break
    return results, errors


def is_stale(build: Build, days: int = 183) -> bool:
    return build.date is not None and (dt.date.today() - build.date).days > days
