# -*- coding: utf-8 -*-
"""Testy R2: wyszukiwarka BIP (bez sieci - HTML podawany z ręki)."""

from bs4 import BeautifulSoup

import bip_search


def _soup(html):
    return BeautifulSoup(html, "html.parser")


HOME_HTML = ('<html><body><h1>Dane podstawowe</h1>'
             '<a href="/1/dane-podstawowe">Dane podstawowe</a>'
             '<a href="/20/rada-gminy">Rada gminy</a>'
             '</body></html>')

RESULTS_HTML = ('<html><body><h2>Wyniki wyszukiwania: nabór rady nadzorczej</h2>'
                '<a href="/7718/nabor-na-czlonkow-rady-nadzorczej">'
                'Nabór na członków rady nadzorczej spółki komunalnej</a>'
                '<a href="/7720/nabor-na-prezesa-zarzadu">'
                'Nabór na prezesa zarządu</a>'
                '<a href="/4068/ogloszenia-i-komunikaty">Ogłoszenia i komunikaty</a>'
                '</body></html>')


class TestLooksLikeHomepage:
    def test_strona_glowna_wykryta(self):
        """System bez wyszukiwarki zwraca stronę główną - trzeba to odsiać."""
        assert bip_search._looks_like_homepage(
            "nabór rady nadzorczej", _soup(HOME_HTML)) is True

    def test_wyniki_nie_sa_strona_glowna(self):
        assert bip_search._looks_like_homepage(
            "nabór rady nadzorczej", _soup(RESULTS_HTML)) is False


class TestExtractEntries:
    def test_znajduje_wpis_o_radzie_nadzorczej(self):
        out = bip_search._extract_entries(
            _soup(RESULTS_HTML), "https://bip.test.pl/?szukaj=x")
        assert len(out) == 1
        text, href = out[0]
        assert "rady nadzorczej" in text.lower()
        assert href == "https://bip.test.pl/7718/nabor-na-czlonkow-rady-nadzorczej"

    def test_odrzuca_nabor_na_zarzad(self):
        out = bip_search._extract_entries(
            _soup(RESULTS_HTML), "https://bip.test.pl/?szukaj=x")
        assert all("zarządu" not in t.lower() for t, _ in out)

    def test_odrzuca_menu_bez_numeru_wpiu(self):
        """Link do sekcji (/4068/...#menu) nie jest wpisem, ale /4068/... tak."""
        html = ('<a href="/20/rada-gminy">Rada gminy informacje</a>'
                '<a href="/7718/nabor-czlonkow-rady-nadzorczej">'
                'Nabór kandydatów na członka rady nadzorczej</a>')
        out = bip_search._extract_entries(_soup(html), "https://bip.test.pl/")
        assert len(out) == 1

    def test_limit_wpisow(self):
        html = "".join(
            f'<a href="/{7700+i}/nabor-czlonkow-rady-nadzorczej-{i}">'
            f'Nabór kandydatów na członka rady nadzorczej {i}</a>'
            for i in range(12))
        out = bip_search._extract_entries(_soup(html), "https://bip.test.pl/")
        assert len(out) == bip_search.MAX_ENTRIES_PER_QUERY

    def test_inna_domena_odrzucona(self):
        html = ('<a href="https://inny.pl/7718/nabor-rady-nadzorczej">'
                'Nabór na członka rady nadzorczej</a>')
        out = bip_search._extract_entries(_soup(html), "https://bip.test.pl/")
        assert out == []


class TestSearchSite:
    def test_nie_wspierana_szukaj_daje_puste(self, monkeypatch):
        """BIP bez wyszukiwarki zwraca stronę główną na każde zapytanie."""
        monkeypatch.setattr(bip_search, "_fetch",
                            lambda url, timeout=15: HOME_HTML)
        monkeypatch.setattr(bip_search.time, "sleep", lambda s: None)
        assert bip_search.search_site("https://bip.test.pl") == []

    def test_znalezione_wpisy_koncza_szukanie(self, monkeypatch):
        """Gdy jeden wzorzec da wyniki, nie sprawdzamy kolejnych."""
        calls = []

        def fake_fetch(url, timeout=15):
            calls.append(url)
            return RESULTS_HTML

        monkeypatch.setattr(bip_search, "_fetch", fake_fetch)
        monkeypatch.setattr(bip_search.time, "sleep", lambda s: None)
        out = bip_search.search_site("https://bip.test.pl")
        assert len(out) == 1
        assert out[0]["_direct"] is True
        assert out[0]["dork"].startswith("szukaj:")
        # pierwszy wzorzec zadziałał - nie powinno być prób innych wzorców
        assert "/?szukaj=" in calls[0]

    def test_brak_sieci_nie_wysypuje(self, monkeypatch):
        monkeypatch.setattr(bip_search, "_fetch", lambda url, timeout=15: None)
        monkeypatch.setattr(bip_search.time, "sleep", lambda s: None)
        assert bip_search.search_site("https://bip.test.pl") == []


class TestNoticeSection:
    def test_dzial_bip_net_pl_rozpoznany(self):
        assert bip_search._is_notice_section_url(
            "https://gasawa.bip.net.pl/?c=230") is True

    def test_strona_wynikow_nie_jest_dzialem(self):
        assert bip_search._is_notice_section_url(
            "https://bip.test.pl/?szukaj=nabór") is False

    def test_znany_adres_dzialu_bip_net_pl(self):
        soup = _soup(HOME_HTML)
        found = bip_search._find_notice_sections(soup, "https://gasawa.bip.net.pl")
        assert "https://gasawa.bip.net.pl/?c=230" in found

    def test_dzial_z_menu(self):
        html = ('<a href="/4068/ogloszenia-i-komunikaty">'
                'Ogłoszenia i komunikaty</a>')
        found = bip_search._find_notice_sections(_soup(html), "https://bip.x.pl")
        assert "https://bip.x.pl/4068/ogloszenia-i-komunikaty" in found


class TestNonRecruitFilter:
    def test_uchwala_odrzucona(self):
        html = ('<a href="/7718/uchwala-nr-xxx-194-2026">'
                'Uchwała Nr XXX/194/2026 Rady Miejskiej w sprawie budżetu</a>')
        out = bip_search._extract_entries(
            _soup(html), "https://bip.x.pl/4068/ogloszenia-i-komunikaty")
        assert out == []

    def test_zarzadzenie_odrzucone(self):
        html = ('<a href="/7719/zarzadzenie-nr-271-2026">'
                'Zarządzenie Nr 271/2026 Burmistrza w sprawie zmian</a>')
        out = bip_search._extract_entries(
            _soup(html), "https://bip.x.pl/4068/ogloszenia-i-komunikaty")
        assert out == []

    def test_ogloszenie_o_naborze_w_dziale_zostaje(self):
        html = ('<a href="/7720/ogloszenie-nr-ood-2110">'
                'Ogłoszenie Nr OOD.2110.3.2026 o naborze na wolne stanowisko</a>')
        out = bip_search._extract_entries(
            _soup(html), "https://bip.x.pl/4068/ogloszenia-i-komunikaty")
        assert len(out) == 1


class TestEntryTitle:
    def test_czytaj_dalej_zastepowane_kontekstem(self):
        html = ('<div><h3>Ogłoszenie o naborze na członka rady nadzorczej</h3>'
                '<a href="/?a=1234">Czytaj dalej</a></div>')
        soup = _soup(html)
        anchor = soup.find("a")
        title = bip_search._entry_title(anchor, "Czytaj dalej")
        assert "rady nadzorczej" in title.lower()
