# -*- coding: utf-8 -*-
"""Testy pogłębionego skanu JST (R3) i priorytetu sekcji."""

import direct_sources as ds
from bs4 import BeautifulSoup


def _soup(html):
    return BeautifulSoup(html, "html.parser")


class TestSectionPriority:
    def test_sekcje_ogloszen_maja_priorytet_nad_menu(self):
        """Limit podstron nie może zjadać samego menu podmiotowego."""
        html = ('<a href="/2/menu-podmiotowe">Menu podmiotowe</a>'
                '<a href="/2369/aktualnosci">Aktualności</a>'
                '<a href="/4068/ogloszenia-i-komunikaty">Ogłoszenia i komunikaty</a>')
        out = ds._section_links(_soup(html), "https://bip.x.pl", 1)
        assert out == ["https://bip.x.pl/2369/aktualnosci"]

    def test_menu_jako_fallback_gdy_brak_sekcji(self):
        """BIP24: strona główna ma tylko menu podmiotowe/przedmiotowe."""
        html = ('<a href="/2/menu-podmiotowe">Menu podmiotowe</a>'
                '<a href="/4066/menu-przedmiotowe">Menu przedmiotowe</a>')
        out = ds._section_links(_soup(html), "https://bip.x.pl", 2)
        assert len(out) == 2
        assert "https://bip.x.pl/2/menu-podmiotowe" in out

    def test_menu_po_sekcjach_gdy_zostaje_miejsce(self):
        html = ('<a href="/2/menu-podmiotowe">Menu podmiotowe</a>'
                '<a href="/2369/aktualnosci">Aktualności</a>')
        out = ds._section_links(_soup(html), "https://bip.x.pl", 2)
        assert out[0] == "https://bip.x.pl/2369/aktualnosci"
        assert out[1] == "https://bip.x.pl/2/menu-podmiotowe"


class TestJstDeepScan:
    def test_jst_skanuje_podstrony(self, monkeypatch, tmp_path):
        """JST musi dostawać deep=True - bez tego skan dawał 0 kandydatów."""
        monkeypatch.chdir(tmp_path)
        calls = []

        def fake_scan(entries, label, max_links_per_source, delay, seen, results,
                      deep=False, max_subpages=0):
            calls.append({"label": label, "deep": deep,
                          "max_links": max_links_per_source,
                          "max_subpages": max_subpages})

        monkeypatch.setattr(ds, "_scan_entries", fake_scan)
        monkeypatch.setattr(ds, "_load_jst_registry",
                            lambda: [{"name": "Gmina Test", "slug": "/t",
                                      "url": "https://bip.test.pl"}])
        monkeypatch.setattr(ds, "_load_jst_urls", lambda: {})
        ds.collect(jst_window=1)
        jst = [c for c in calls if c["label"] == "BIP JST"]
        assert jst, "Faza 0b nie została wywołana"
        assert jst[0]["deep"] is True
        assert jst[0]["max_links"] == ds.JST_MAX_LINKS
        assert jst[0]["max_subpages"] >= 1

    def test_whitelist_nadal_deep(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        calls = []

        def fake_scan(entries, label, max_links, delay, seen, results,
                      deep=False, max_subpages=0):
            calls.append({"label": label, "deep": deep})

        monkeypatch.setattr(ds, "_scan_entries", fake_scan)
        monkeypatch.setattr(ds, "_load_jst_registry", lambda: [])
        ds.collect(jst_window=1)
        assert calls[0]["deep"] is True
