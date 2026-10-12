import json

import json

from curseofdroid.catalog.base import hashes_from
from curseofdroid.catalog.providers import CrDroid, DerpFest, LineageOS, OrangeFox, PixelOS, TWRP, find_builds
from curseofdroid.platform.net import NotFound


def fetcher(pages: dict):
    def fetch(url):
        if url not in pages:
            raise NotFound(url)
        v = pages[url]
        return v if isinstance(v, str) else json.dumps(v)
    return fetch


def test_hash_classification_by_length():
    assert hashes_from(sha256="a" * 32) == {"md5": "a" * 32}  # PixelOS puts md5 in "sha256"
    assert hashes_from(unknown="B" * 64) == {"sha256": "b" * 64}
    assert hashes_from(sha256="xyz") == {}


def test_lineageos_rom_zip_first_and_android_version():
    api = "https://download.lineageos.org/api/v2/devices/oriole"
    f = fetcher({api: {"name": "Pixel 6", "info_url": "https://wiki.lineageos.org/devices/oriole"},
                 api + "/builds": [{"datetime": 1791158744, "type": "nightly", "version": "23.2", "files": [
                     {"filename": "boot.img", "url": "u/boot.img", "size": 1, "sha256": "1" * 64},
                     {"filename": "lineage-23.2-x-oriole-signed.zip", "url": "u/rom.zip", "size": 2,
                      "sha256": "2" * 64}]}]})
    [b] = LineageOS(f).builds("oriole")
    assert b.main.filename.endswith(".zip") and b.android == "16" and b.device_name == "Pixel 6"
    assert b.main.hashes == {"sha256": "2" * 64}


def test_crdroid_newest_branch_with_device(monkeypatch):
    raw = "https://raw.githubusercontent.com/crdroidandroid/android_vendor_crDroidOTA"
    f = fetcher({raw + "/16.0/lavender.json": {"response": [{
        "filename": "crDroidAndroid-16.0-x-lavender-v12.12.zip", "download": "https://sf/x.zip",
        "timestamp": 1791467242, "sha256": "3" * 64, "md5": "4" * 32, "size": 5, "version": "12.12",
        "oem": "Xiaomi", "device": "Redmi Note 7"}]}})
    p = CrDroid(f)
    monkeypatch.setattr(p, "branches", lambda: ["17.0", "16.0", "15.0"])
    [b] = p.builds("lavender")
    assert b.android == "16" and b.version == "12.12" and set(b.main.hashes) == {"sha256", "md5"}
    assert b.device_name == "Xiaomi Redmi Note 7"


def test_derpfest_id_is_sha256_and_pixelos_md5():
    d = fetcher({"https://raw.githubusercontent.com/DerpFest-AOSP/Updater-Stuff/master/Pong.json": {"response": [{
        "datetime": 1783773153, "filename": "DerpFest.zip", "id": "5" * 64, "url": "https://sf/d", "size": 1,
        "version": "v16.2", "romtype": "Official"}]}})
    assert DerpFest(d).builds("Pong")[0].main.hashes == {"sha256": "5" * 64}
    p = fetcher({"https://raw.githubusercontent.com/PixelOS-AOSP/official_devices/seventeen/API/updater/G.json": [
        {"datetime": 1, "version": "14.0", "type": "ci",
         "files": [{"filename": "PixelOS_G.zip", "url": "https://sf/p", "size": 1, "sha256": "6" * 32}]}]})
    assert PixelOS(p).builds("G")[0].main.hashes == {"md5": "6" * 32}


def test_twrp_listing_referer_and_order():
    page = ('<a href="/lavender/twrp-3.6.2_9-0-lavender.img.html">x</a>'
            '<a href="/lavender/twrp-3.7.0_9-0-lavender.img.html">y</a>'
            '<a href="/lavender/twrp-3.10.0_9-0-lavender.img.html">z</a>')
    f = fetcher({"https://dl.twrp.me/lavender/": page,
                 "https://dl.twrp.me/lavender/twrp-3.10.0_9-0-lavender.img.sha256": "7" * 64 + "  f\n"})
    p = TWRP(f)
    builds = p.builds("lavender")
    assert [b.version for b in builds] == ["3.10.0_9-0", "3.7.0_9-0", "3.6.2_9-0"]
    b = builds[0]
    assert b.main.headers["Referer"] == b.main.url + ".html"
    p.fill_hash(b)
    assert b.main.hashes == {"sha256": "7" * 64}


def test_orangefox_mirror_and_md5():
    url = ("https://api.orangefox.download/v3/releases/?codename=lavender&type=stable&sort=date_desc&limit=10")
    f = fetcher({url: {"data": [{"_id": "abc", "filename": "OrangeFox-R12.zip", "version": "R12.0", "date": 1,
                                 "md5": "8" * 32, "size": 3, "variant": "kernel_419", "device_id": "d",
                                 "mirrors": {"DL": "https://dl.orangefox.download/abc"}}]}})
    [b] = OrangeFox(f).builds("lavender")
    assert b.main.url == "https://dl.orangefox.download/abc" and b.variant == "kernel_419"


def test_find_builds_tries_aliases_and_isolates_errors():
    class Broken(LineageOS):
        name = "Broken"

        def builds(self, c):
            raise RuntimeError("down")

    f = fetcher({"https://download.lineageos.org/api/v2/devices/real": {"name": "X"},
                 "https://download.lineageos.org/api/v2/devices/real/builds": [
                     {"version": "21.0", "datetime": 1, "files": [{"filename": "a.zip", "url": "u"}]}]})
    results, errors = find_builds(["alias", "real"], [Broken, LineageOS], fetch=f)
    assert list(results) == ["LineageOS"] and results["LineageOS"][0].codename == "real"
    assert errors and "Broken" in errors[0]


def test_gsi_fit_and_asset_selection():
    from pathlib import Path

    from curseofdroid.catalog.gsi import gsi_fit, trebledroid_builds
    from curseofdroid.device.profile import from_props
    from curseofdroid.transport.adb import parse_getprop
    fix = Path(__file__).parent / "fixtures"
    atu = from_props(parse_getprop((fix / "huawei_atu_l21_lineage17_getprop.txt").read_text()))
    assert not gsi_fit(atu).ok and "system-as-root" in gsi_fit(atu).reasons[0]
    oppo = from_props(parse_getprop((fix / "oppo_cph2801_android16_getprop.txt").read_text()))
    releases = [{"tag_name": "ci-2", "published_at": "2025-06-17T00:00:00Z", "html_url": "u", "assets": [
        {"name": "system-td-arm64-vanilla-old.img.xz", "browser_download_url": "o", "size": 2},
        {"name": "system-td-arm32_binder64-vanilla.img.xz", "browser_download_url": "a32", "size": 3},
        {"name": "system-td-arm64-vanilla.img.xz", "browser_download_url": "n", "size": 1},
        {"name": "manifest.xml", "browser_download_url": "m", "size": 1}]}]
    builds = trebledroid_builds(oppo, fetch=lambda url: releases)
    assert [b.main.url for b in builds] == ["n", "o"]  # regular first, arm64 only
    assert "-old" in builds[1].variant


def test_evolutionx_newest_branch_with_device_and_vanilla(monkeypatch):
    from curseofdroid.catalog.providers import EvolutionX
    raw = "https://raw.githubusercontent.com/Evolution-X/OTA"
    entry = lambda f, maintained=True: {"response": [{  # noqa: E731
        "filename": f, "download": "https://cdn/x", "timestamp": 1789445766, "sha256": "9" * 64, "size": 1,
        "version": "11.11", "currently_maintained": maintained}]}
    f = fetcher({raw + "/bka/builds/oriole.json": entry("Evo-16-oriole.zip", maintained=False),
                 raw + "/bka-vanilla/builds/oriole.json": entry("Evo-16-oriole-Vanilla.zip"),
                 raw + "/vic/builds/oriole.json": entry("Evo-15-oriole.zip")})
    p = EvolutionX(f)
    monkeypatch.setattr(p, "branches", lambda: ["cnb", "bka", "vic", "udc"])
    builds = p.builds("oriole")
    assert [b.main.filename for b in builds] == ["Evo-16-oriole.zip", "Evo-16-oriole-Vanilla.zip"]
    assert builds[0].android == "16" and "Google" in builds[0].variant and "vanilla" in builds[1].variant
    assert builds[0].notes == "not maintained anymore"
    assert p.builds("lavender") == []


def test_evolutionx_branch_order_from_api():
    from curseofdroid.catalog.providers import EvolutionX
    api = "https://api.github.com/repos/Evolution-X/OTA/branches?per_page=100"
    names = ["bka", "bka-vanilla", "cnb", "cnb-vanilla", "udc", "vic"]
    p = EvolutionX(fetcher({api: [{"name": n} for n in names]}))
    assert p.branches() == ["cnb", "bka", "vic", "udc"]


PLAY = ('Retail Branding,Marketing Name,Device,Model\n'
        '"Redmi","Redmi Note 7","lavender","Redmi Note 7"\n'
        '"Redmi","Redmi  Note  7","lavender","Redmi Note 7"\n'
        '"Blaupunkt","BLAUPUNKT","lavender","4K SMART TV"\n'
        '"FPD","FPD","lavender","EcoTV Plus C"\n'
        '"ZTE","Z717VL","lavender","Z717VL"\n'
        '"Huawei","HUAWEI Y6 2018","HWATU-QG","ATU-L21"\n'
        '"Huawei","HUAWEI Y6 Prime 2018","HWATU-QG","ATU-L31"\n'
        '"Samsung","Galaxy Tab A","gta","SM-T500"\n').encode("utf-16")


def test_market_names_only_phones_of_the_right_brand():
    from curseofdroid.catalog.deviceinfo import market_names, play_rows
    fetch = lambda url, cache_days=1: PLAY  # noqa: E731
    rows = play_rows("lavender", fetch)
    names = market_names(rows, vendor="Xiaomi")
    assert [(m.brand, m.name, m.models) for m in names] == [("Redmi", "Redmi Note 7", ["Redmi Note 7"])]
    # without a known vendor TVs are still dropped, other phones stay
    assert {m.brand for m in market_names(rows)} == {"Redmi", "ZTE"}
    assert market_names(play_rows("gta", fetch)) == []  # tablet


def test_play_lookup_by_model_number():
    from curseofdroid.catalog.deviceinfo import market_names, play_rows
    rows = play_rows("atu_l21", lambda url, cache_days=1: PLAY, models=["ATU-L21"])
    assert [m.name for m in market_names(rows, "HUAWEI")] == ["HUAWEI Y6 2018", "HUAWEI Y6 Prime 2018"]


def test_wiki_variants_and_specs():
    from curseofdroid.catalog.deviceinfo import LINEAGE_WIKI, device_info
    pages = {LINEAGE_WIKI.format(c="marble_variant1"): "vendor: Xiaomi\nname: POCO F5 (Global)\nmodels: [A]\n"
                                                       "soc: SD 7+ Gen 2\ncpu_cores: '8'\ncpu_freq: 3 GHz\n"
                                                       "screen: {size: 6.67, resolution: '1080x2400'}\n"
                                                       "recovery_boot: hold <kbd>Volume Up</kbd>\n",
             LINEAGE_WIKI.format(c="marble_variant2"): "vendor: Xiaomi\nname: Redmi Note 12 Turbo\nmodels: [B]\n"}
    info = device_info("marble", play_fetch=lambda url, cache_days=1: PLAY, wiki_fetch=fetcher(pages))
    assert info.name == "POCO F5 (Global) / Redmi Note 12 Turbo" and info.models == ["A", "B"]
    assert info.specs["CPU"] == "8 cores (3 GHz)" and info.specs["Recovery mode"] == "hold Volume Up"
    assert info.specs["Screen"].startswith('6.67"')


def test_new_rom_providers():
    from curseofdroid.catalog.providers import GrapheneOS, ParanoidAndroid, RisingOS
    pa = fetcher({"https://api.paranoidandroid.co/updates/alioth": {"updates": [
        {"date": "2024-07-08", "datetime": "1720000000", "filename": "old.zip", "url": "u1", "size": "5",
         "recovery_sha256": "1" * 64, "version": "Uvite", "version_code": "6", "android_version": "14"},
        {"date": "2024-08-11", "datetime": "1723389364", "filename": "new.zip", "url": "u2", "size": "7",
         "recovery_sha256": "2" * 64, "fastboot": "https://b/new-image.zip", "fastboot_sha256": "3" * 64,
         "version": "Uvite", "version_code": "7", "android_version": "14", "build_type": "Beta"}]}})
    b = ParanoidAndroid(pa).builds("alioth")
    assert b[0].main.filename == "new.zip" and b[0].main.size == 7 and len(b[0].artifacts) == 2
    base = "https://raw.githubusercontent.com/RisingOS-Revived/official_devices/fifteen/OTA/device"
    one = {"response": [{"filename": "r.zip", "download": "d", "timestamp": 1, "sha256": "4" * 64, "size": 1,
                         "version": "8"}]}
    r = RisingOS(fetcher({f"{base}/CORE/Pong.json": one})).builds("Pong")
    assert [x.variant for x in r] == ["vanilla (no Google apps)"]
    g = GrapheneOS(fetcher({"https://releases.grapheneos.org/oriole-stable": "2026100600 1791330262 oriole stable\n"}))
    [gb] = g.builds("oriole")
    assert gb.main.url.endswith("oriole-install-2026100600.zip") and "web installer" in gb.notes
    assert g.builds("lavender") == []


def test_ended_projects_use_live_mirrors_and_say_so():
    from curseofdroid.catalog.providers import ENDED, ArrowOS, HavocOS, PixelExperience
    raw = "https://raw.githubusercontent.com"
    pe = PixelExperience(fetcher({f"{raw}/PixelExperience/official_devices/master/devices.json": [
        {"codename": "lavender", "brand": "Xiaomi", "name": "Redmi Note 7",
         "supported_versions": [{"version_code": "thirteen"}, {"version_code": "thirteen_plus"}]}]}))
    calls = []
    pe.fetch_live = lambda url: (calls.append(url), json.dumps(
        {"datetime": 1706252520, "filename": "PE.zip", "id": "a" * 32, "size": 3, "url": "https://dl/x"}))[1]
    [b] = pe.builds("lavender")
    assert b.version == "13 Plus" and b.main.hashes == {"md5": "a" * 32} and b.notes == ENDED
    assert calls[0].endswith("/lavender/thirteen_plus")  # newest version first, fetched without cache
    arrow = ArrowOS(fetcher({f"{raw}/ArrowOS/arrow_ota/master/arrow-13.1_gapps_builds_official.json": {
        "lavender": [{"filename": "Arrow-v13.1-lavender-OFFICIAL-20240204-GAPPS.zip", "date": "2024-02-04",
                      "sha256": "b" * 64, "size": "5", "version": "v13.1"}]}}))
    [a] = arrow.builds("lavender")
    assert a.main.url == ("https://sourceforge.net/projects/arrow-os/files/arrow-13.1/official/lavender/"
                          "Arrow-v13.1-lavender-OFFICIAL-20240204-GAPPS.zip/download")
    assert a.main.size == 5 and a.android == "13"
    havoc = HavocOS(fetcher({f"{raw}/Havoc-OS/OTA/thirteen/gapps/alioth.json": {
        "filename": "Havoc.zip", "filehash": "c" * 32, "size": 1, "datetime": 1, "version": "6.0"}}))
    [h] = havoc.builds("alioth")
    assert h.main.url.startswith("https://sourceforge.net/projects/havoc-os/files/alioth/") and h.android == "13"


def test_page_only_and_installer_projects():
    from curseofdroid.catalog.providers import EOS, CalyxOS, IodeOS, ProjectElixir
    el = ProjectElixir(fetcher({"https://projectelixiros.com/assets/json/download.json": [{"deviceDetails": [
        {"codeName": "vince", "thirteenbuildVersion": "v3.3", "deviceStatus": "discontinued",
         "downloadLink": "https://www.pling.com/p/1/"}]}]}))
    [e] = el.builds("vince")
    assert not e.main.direct and e.main.url == "https://www.pling.com/p/1/" and "discontinued" in e.notes
    yml = ("stable:\n- name: Pixel 6\n  codename: oriole\n  version: 7.2.5.20\n  android: '16'\n"
           "  factory_link: https://release.calyxos.org/factory/oriole-factory.zip\n  factory_sha256: " + "d" * 64 +
           "\n  date: '2026-09-09'\n")
    [c] = CalyxOS(fetcher({"https://raw.githubusercontent.com/CalyxOS/calyxos.org/main/pages/_data/downloads.yml":
                           yml})).builds("oriole")
    assert c.main.hashes == {"sha256": "d" * 64} and "device-flasher" in c.notes
    eos = EOS(fetcher({"https://ota.ecloud.global/api/v1/FP5/official/1": {"response": [
        {"datetime": 2, "filename": "e-new.zip", "url": "u2", "md5sum": "e" * 32, "version": "4.3",
         "android_version": "15", "size": 1},
        {"datetime": 1, "filename": "e-old.zip", "url": "u1", "md5sum": "f" * 32, "version": "4.2", "size": 1}]}}))
    assert [b.main.filename for b in eos.builds("FP5")] == ["e-new.zip", "e-old.zip"]
    io = IodeOS(fetcher({"https://ota.iode.tech/v6-release/FP5.json": {"response": [
        {"datetime": 1, "filename": "iode.zip", "id": "9" * 64, "size": 1, "url": "u", "version": "7.9"}]}}))
    assert io.builds("FP5")[0].main.hashes == {"sha256": "9" * 64}
