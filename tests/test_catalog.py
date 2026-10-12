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
