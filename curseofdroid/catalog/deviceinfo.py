"""What phone is a codename? Marketing names and specs from public catalogs.

- Google Play's supported-devices list (play_public/supported_devices.csv): every Play-certified device with
  brand, marketing name, device (codename) and model. Many codenames are shared with unrelated products
  ("lavender" is a Redmi Note 7 and dozens of smart TVs), so only phones are kept: TV/box/tablet/watch entries are
  dropped, and when the brand is known from a ROM catalog only that brand family remains.
- LineageOS wiki device data (_data/devices/<codename>.yml): SoC, RAM, storage, screen, battery, release year,
  model numbers, how to reach recovery/download mode.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from ..platform.net import NotFound, fetch_bytes, fetch_text

PLAY_CSV = "https://storage.googleapis.com/play_public/supported_devices.csv"
LINEAGE_WIKI = "https://raw.githubusercontent.com/LineageOS/lineage_wiki/main/_data/devices/{c}.yml"

_NOT_PHONE = re.compile(r"(\w*tv\b|\b(?:box|stb|set[- ]?top|tab|tablet|pad|watch|"
                        r"chromebook|projector|car|auto|display|monitor|dongle|stick|kiosk|pos|terminal|"
                        r"4k|uhd|qled|soundbar|speaker)\b)", re.I)
# brand families: a ROM catalog's vendor -> brands that sell the same hardware
FAMILIES = [{"xiaomi", "redmi", "poco", "mi"}, {"oneplus", "oppo", "realme"}, {"motorola", "lenovo", "moto"},
            {"huawei", "honor"}, {"samsung"}, {"google"}, {"sony"}, {"nothing", "cmf"}, {"asus"}, {"nokia", "hmd"},
            {"fairphone"}, {"lg"}, {"zte", "nubia"}, {"vivo", "iqoo"}, {"tecno", "infinix", "itel"}]


@dataclass
class MarketName:
    brand: str
    name: str
    models: list[str] = field(default_factory=list)


@dataclass
class DeviceInfo:
    codename: str
    vendor: str = ""
    name: str = ""  # LineageOS wiki name
    phones: list[MarketName] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)  # label -> value, display order
    models: list[str] = field(default_factory=list)  # model numbers from the wiki


def _family(brand: str) -> set[str]:
    b = brand.lower().strip()
    for fam in FAMILIES:
        if b in fam:
            return fam
    return {b}


def is_phone(row: dict) -> bool:
    text = f"{row.get('Marketing Name', '')} {row.get('Model', '')}"
    return not _NOT_PHONE.search(text)


def play_rows(codename: str, fetch=None, models: list[str] = ()) -> list[dict]:
    """Rows whose Device is the codename. ROM codenames sometimes differ from the vendor's Play device name
    (Huawei Y6 2018: ROMs say atu_l21, Play says HWATU-QG); a known model number then finds the Play name."""
    raw = (fetch or fetch_bytes)(PLAY_CSV, cache_days=7)
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    names = {codename.lower()}
    wanted_models = {m.lower() for m in models if m}
    names |= {(r.get("Device") or "").lower() for r in rows if (r.get("Model") or "").lower() in wanted_models}
    return [r for r in rows if (r.get("Device") or "").lower() in names]


def market_names(rows: list[dict], vendor: str = "") -> list[MarketName]:
    rows = [r for r in rows if is_phone(r)]
    if vendor:
        fam = _family(vendor)
        same = [r for r in rows if (r.get("Retail Branding") or "").lower().strip() in fam]
        rows = same or rows  # unknown branding spellings: keep the phones rather than show nothing
    out: dict[tuple[str, str], MarketName] = {}
    for r in rows:
        brand = (r.get("Retail Branding") or "").strip()
        name = re.sub(r"\s+", " ", (r.get("Marketing Name") or "").strip()) or r.get("Model", "")
        key = (brand.lower(), name.lower())
        m = out.setdefault(key, MarketName(brand, name))
        model = (r.get("Model") or "").strip()
        if model and model not in m.models:
            m.models.append(model)
    return list(out.values())


def wiki(codename: str, fetch=fetch_text) -> list[dict]:
    """The device's wiki entry; devices sold in several regional versions have <codename>_variantN.yml files."""
    import yaml
    out = []
    for name in [codename] + [f"{codename}_variant{i}" for i in range(1, 6)]:
        try:
            data = yaml.safe_load(fetch(LINEAGE_WIKI.format(c=name)))
        except NotFound:
            if name == codename or name.endswith("_variant1"):
                continue
            break
        if isinstance(data, dict):
            out.append(data)
        if name == codename:
            break
    return out


def _specs(w: dict) -> dict[str, str]:
    s: dict[str, str] = {}

    def put(label, value):
        if value not in (None, "", [], {}):
            s[label] = str(value)

    put("Released", w.get("release"))
    put("SoC", w.get("soc"))
    cores, freq = w.get("cpu_cores"), w.get("cpu_freq")
    put("CPU", f"{cores} cores" + (f" ({freq})" if freq else "") if cores else w.get("cpu"))
    put("GPU", w.get("gpu"))
    put("RAM", w.get("ram"))
    put("Storage", w.get("storage"))
    scr = w.get("screen")
    if isinstance(scr, dict):
        put("Screen", " · ".join(str(x) for x in (f'{scr.get("size")}"' if scr.get("size") else "", scr.get("resolution"),
                                                 scr.get("technology"),
                                                 f'{scr.get("refresh_rate")} Hz' if scr.get("refresh_rate") else "")
                                 if x))
    bat = w.get("battery")
    if isinstance(bat, dict) and bat.get("capacity"):
        put("Battery", f'{bat["capacity"]} mAh' + (" (removable)" if bat.get("removable") else ""))
    cams = w.get("cameras")
    if isinstance(cams, list):
        put("Cameras", ", ".join(str(c.get("info")) for c in cams if isinstance(c, dict) and c.get("info")))
    put("Architecture", w.get("architecture") if isinstance(w.get("architecture"), str) else "")
    put("Recovery mode", re.sub(r"</?kbd>", "", str(w.get("recovery_boot") or "")))
    put("Download/fastboot mode", re.sub(r"</?kbd>", "", str(w.get("download_boot") or "")))
    return s


def device_info(codename: str, vendor_hint: str = "", models: list[str] = (), play_fetch=None,
                wiki_fetch=fetch_text) -> DeviceInfo:
    info = DeviceInfo(codename)
    variants: list[dict] = []
    try:
        variants = wiki(codename, wiki_fetch)
    except Exception:
        pass
    if variants:
        w = variants[0]
        info.vendor = str(w.get("vendor") or "")
        info.name = " / ".join(dict.fromkeys(str(v.get("name")) for v in variants if v.get("name")))
        info.models = list(dict.fromkeys(str(m) for v in variants for m in v.get("models") or []))
        info.specs = _specs(w)
    try:
        info.phones = market_names(play_rows(codename, play_fetch, [*models, *info.models]),
                                   info.vendor or vendor_hint)
    except Exception:
        pass
    if not info.vendor and info.phones:
        info.vendor = info.phones[0].brand
    return info
