# -*- coding: utf-8 -*-
"""Rejestr sekcji ogłoszeń BIP: ładowanie i skan od sekcji."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load_discovery():
    spec = importlib.util.spec_from_file_location(
        "discover_sections", ROOT / "tools" / "discover_sections.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


disc = _load_discovery()

SECTION_HTML = """
<html><body><h1>Urząd Gminy Test - Nabory</h1>
<a href="/12345/nabor-na-czlonka-rady-nadzorczej-spolki">Nabór na członka Rady Nadzorczej spółki</a>
</body></html>
"""
HOME_HTML = """
<html><body><a href="/nabory">Nabory</a></body></html>
"""
EMPTY_HTML = "<html><body>Brak ogłoszeń</body></html>"


class TestLoadSections:
    def test_oba_formaty_wpisu(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "bip_sections.json").write_text(json.dumps({
            "/a": {"url": "https://a.bip.pl/nabory", "items": 3},
            "/b": "https://b.bip.pl/nabory",
        }), encoding="utf-8")
        out = disc.ds._load_jst_sections()
        assert out == {"/a": "https://a.bip.pl/nabory",
                       "/b": "https://b.bip.pl/nabory"}

    def test_brak_pliku(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert disc.ds._load_jst_sections() == {}


class TestScanFromSection:
    def test_skan_zaczyna_od_sekcji(self, monkeypatch):
        fetched = []

        def fake_fetch(url):
            fetched.append(url)
            return SECTION_HTML if "nabory" in url else HOME_HTML

        monkeypatch.setattr(disc.ds, "_fetch_html", fake_fetch)
        results, seen, stats = [], set(), {}
        disc.ds._scan_entries(
            [{"name": "Gmina Test", "url": "https://bip.test.pl",
              "section": "https://bip.test.pl/nabory"}],
            "BIP JST", 2, 0, seen, results, deep=False, stats=stats)
        assert fetched[0] == "https://bip.test.pl/nabory"
        assert len(results) == 1
        assert "rady-nadzorczej" in results[0]["link"]
        assert stats["jst_section_scan"] == 1
        assert "jst_section_fallback" not in stats

    def test_pusta_sekcja_wraca_do_domu(self, monkeypatch):
        fetched = []

        def fake_fetch(url):
            fetched.append(url)
            if url.endswith("/nabory"):
                return EMPTY_HTML
            return SECTION_HTML

        monkeypatch.setattr(disc.ds, "_fetch_html", fake_fetch)
        results, seen, stats = [], set(), {}
        disc.ds._scan_entries(
            [{"name": "Gmina Test", "url": "https://bip.test.pl",
              "section": "https://bip.test.pl/nabory"}],
            "BIP JST", 2, 0, seen, results, deep=False, stats=stats)
        assert fetched == ["https://bip.test.pl/nabory", "https://bip.test.pl"]
        assert stats["jst_section_fallback"] == 1
        assert len(results) == 1

    def test_bez_sekcji_skan_domu(self, monkeypatch):
        fetched = []
        monkeypatch.setattr(disc.ds, "_fetch_html",
                            lambda u: (fetched.append(u), SECTION_HTML)[1])
        results, seen, stats = [], set(), {}
        disc.ds._scan_entries([{"name": "Gmina Test", "url": "https://bip.test.pl"}],
                              "BIP JST", 2, 0, seen, results, deep=False, stats=stats)
        assert fetched == ["https://bip.test.pl"]
        assert stats["jst_home_scan"] == 1


class TestDiscoverSection:
    def test_wybiera_sekcje_z_najwiecej_wpisami(self, monkeypatch):
        pages = {
            "https://bip.test.pl": """<html><body>
                <a href="/nabory">Nabory</a>
                <a href="https://inny.bip.pl/nabory">Nabory</a>
                <a href="/aktualnosci">Aktualności</a>
            </body></html>""",
            "https://bip.test.pl/nabory": SECTION_HTML,
            "https://bip.test.pl/nabory?p=2": SECTION_HTML + SECTION_HTML,
        }
        monkeypatch.setattr(disc.ds, "_fetch_html", lambda u: pages.get(u))
        res = disc.discover_section("https://bip.test.pl")
        assert res is not None
        assert res["url"].startswith("https://bip.test.pl/nabory")

    def test_brak_sekcji(self, monkeypatch):
        monkeypatch.setattr(disc.ds, "_fetch_html", lambda u: "<html><body>nic</body></html>")
        assert disc.discover_section("https://bip.test.pl") is None

    def test_nie_pobiera_strony(self, monkeypatch):
        monkeypatch.setattr(disc.ds, "_fetch_html", lambda u: None)
        assert disc.discover_section("https://bip.test.pl") is None
