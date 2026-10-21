# -*- coding: utf-8 -*-
"""Testy direct_sources: linki-kandydaci i okno JST (bez wywołań sieciowych)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from bs4 import BeautifulSoup

from direct_sources import (
    _candidate_links,
    _collect_from_page,
    _section_links,
    jst_daily_slice,
)


def _soup(html: str):
    return BeautifulSoup(html, "html.parser")


def test_candidate_links_filters_by_anchor_text():
    html = ('<html><body>'
            '<a href="/aktualnosci/ogloszenie-nabor">Ogłoszenie o naborze '
            'kandydatów na członka rady nadzorczej</a>'
            '<a href="/kontakt">Kontakt</a>'
            '<a href="/nabor-prezes">Nabór na prezesa zarządu spółki</a>'
            '<a href="/nabor">kandydat</a>'
            '<a href="https://inny.pl/rada">Nabór kandydatów do rady nadzorczej</a>'
            '</body></html>')
    links = _candidate_links(_soup(html), "https://bip.example.pl", 10)
    hrefs = [h for _, h in links]
    texts = [t for t, _ in links]
    # Kotwica naborowa rady nadzorczej + link względny rozwinięty do absolutnego
    assert "https://bip.example.pl/aktualnosci/ogloszenie-nabor" in hrefs
    assert "https://inny.pl/rada" in hrefs
    # Brak "nadzorcz" w tekście kotwicy -> odpada (nabór na zarząd)
    assert all("prezesa" not in t.lower() for t in texts)
    # Tekst krótszy niż 12 znaków -> odpada
    assert "https://bip.example.pl/nabor" not in hrefs


def test_candidate_links_caps_max():
    html = "".join(
        f'<a href="/nabor-{i}">nabór kandydatów do rady nadzorczej {i}</a>'
        for i in range(10))
    links = _candidate_links(_soup(html), "https://bip.example.pl", 3)
    assert len(links) == 3


def test_jst_daily_slice_basic():
    reg = list(range(10))
    out = jst_daily_slice(reg, window=3)
    assert len(out) == 3
    # Deterministyczne: dwa wywołania w tym samym dniu dają ten sam wynik
    assert out == jst_daily_slice(reg, window=3)
    # Wszystkie elementy pochodzą z rejestru i są unikalne
    assert len(set(out)) == 3
    assert set(out) <= set(reg)


def test_jst_daily_slice_wrap_around():
    # Okno większe niż rejestr -> cały rejestr
    reg = list(range(5))
    assert jst_daily_slice(reg, window=10) == reg


def test_jst_daily_slice_pokrywa_caly_rejestr_w_cyklu():
    """Nowy algorytm: każde okno pojawia się raz na cykl, bez pominięć.

    Poprzednia wersja `(day * window) % len` przy 1106 wpisach i oknie 100
    odwiedzała część wpisów dwa razy, a część pomijała.
    """
    reg = list(range(1106))
    seen = set()
    for day in range(1, 13):        # ceil(1106/100) = 12 okien
        seen.update(jst_daily_slice(reg, window=100, day_of_year=day))
    assert seen == set(range(1106))


def test_jst_daily_slice_edge_cases():
    reg = list(range(3))
    # Okno większe niż rejestr -> cały rejestr
    assert jst_daily_slice(reg, window=100) == reg
    # Pusty rejestr / window <= 0 -> []
    assert jst_daily_slice([], window=10) == []
    assert jst_daily_slice(reg, window=0) == []


# --- Pogłębiony skan: sekcje i zbieranie kandydatów ze strony ---

def test_section_links_same_domain_only():
    html = ('<html><body>'
            '<a href="/aktualnosci">Aktualności</a>'
            '<a href="/konkursy">Konkursy</a>'
            '<a href="https://inny.pl/aktualnosci">Aktualności (inna domena)</a>'
            '<a href="/kontakt">Kontakt</a>'
            '</body></html>')
    out = _section_links(_soup(html), "https://bip.example.pl", 5)
    assert out == ["https://bip.example.pl/aktualnosci",
                   "https://bip.example.pl/konkursy"]


def test_section_links_caps_and_excludes_base():
    html = ('<a href="/aktualnosci">Aktualności</a>'
            '<a href="/kariera">Kariera</a>'
            '<a href="/relacje-inwestorskie">Relacje inwestorskie</a>'
            '<a href="/">Strona główna</a>')
    out = _section_links(_soup(html), "https://bip.example.pl", 2)
    assert out == ["https://bip.example.pl/aktualnosci",
                   "https://bip.example.pl/kariera"]


def test_collect_from_page_dedup_and_format():
    html = ('<a href="/7718/nabor-kandydatow-do-rady-nadzorczej">nabór kandydatów do rady nadzorczej</a>'
            '<a href="/7718/nabor-kandydatow-do-rady-nadzorczej">nabór kandydatów do rady nadzorczej (duplikat)</a>'
            '<a href="/7719/nabor-do-rady-nadzorczej-2019">nabór do rady nadzorczej 2019</a>')
    seen, results = set(), []
    added = _collect_from_page(_soup(html), "https://bip.example.pl", 10,
                               "BIP JST", seen, results)
    assert added == 1  # duplikat i stary rocznik odrzucone
    assert results[0]["link"] == "https://bip.example.pl/7718/nabor-kandydatow-do-rady-nadzorczej"
    assert results[0]["_direct"] is True
    assert results[0]["dork"] == "BIP JST"


def test_collect_from_page_odrzuca_menu():
    """Link do działu ma identyczną kotwicę jak ogłoszenie - ale nim nie jest."""
    html = ('<a href="/menu-podmiotowe">Nabór kandydatów do rady nadzorczej - menu</a>'
            '<a href="/ogloszenia">Nabór na członków rady nadzorczej</a>'
            '<a href="/aktualnosci">Ogłoszenie o naborze do rady nadzorczej</a>')
    seen, results = set(), []
    added = _collect_from_page(_soup(html), "https://bip.example.pl", 10,
                               "BIP JST", seen, results)
    assert added == 0
    assert results == []

# --- Filtr portalu gov.pl i rozbicie statystyk (R1 + R4) ---

import direct_sources as ds


def test_is_portal_url_strona_gminy():
    """Strona gminy na gov.pl nie jest BIP-em - nie warto jej skanować."""
    assert ds.is_portal_url(
        "https://www.gov.pl/gmina-banie-mazurskie-warminsko-mazurskie") is True


def test_is_portal_url_bip_na_gov_pl_zostaje():
    """BIP-y hostowane na gov.pl (/web/bip/) mają własną strukturę."""
    assert ds.is_portal_url(
        "https://www.gov.pl/web/bip/gmina-aleksandrow-kujawski") is False


def test_is_portal_url_wlasna_domena():
    assert ds.is_portal_url("https://www.bip.bartniczka.pl") is False
    assert ds.is_portal_url("https://barcin.bip24.pl") is False


def test_collect_uzupelnia_rozbicie(monkeypatch, tmp_path):
    """Faza 0 rozdziela whitelist i JST w statystykach (R4)."""
    monkeypatch.chdir(tmp_path)

    def fake_scan(entries, label, max_links, delay, seen, results, deep=False):
        results.append({"title": "Nabór na członka rady nadzorczej X",
                        "snippet": "", "link": "https://x.pl/1",
                        "dork": label, "_direct": True})

    monkeypatch.setattr(ds, "_scan_entries", fake_scan)
    monkeypatch.setattr(ds, "_load_jst_registry", lambda: [])
    stats = {}
    ds.collect(jst_window=10, stats=stats)
    assert stats["direct_whitelist"] == 1


def test_looks_like_notice_url_bip24():
    assert ds.looks_like_notice_url("https://bip.gogolin.pl/18229/ogloszenie-o-naborze")


def test_looks_like_notice_url_bip_net():
    assert ds.looks_like_notice_url("https://gasawa.bip.net.pl/?a=11018")


def test_looks_like_notice_url_menu_odrzucone():
    assert not ds.looks_like_notice_url("https://bip.x.pl/menu-podmiotowe")
    assert not ds.looks_like_notice_url("https://bip.x.pl/")
    assert not ds.looks_like_notice_url("https://bip.x.pl/ogloszenia")


def test_looks_like_notice_url_techniczne_odrzucone():
    """Linki techniczne z audytu: porównywarka, wydruk, załącznik."""
    assert not ds.looks_like_notice_url(
        "https://bip.piastow.pl/nabor-na-czlonkow-rady/porownaj/3/2")
    assert not ds.looks_like_notice_url(
        "https://www.pfron.org.pl/?tx_invshare_pi1%5BprintD%5D=aHR0")
    assert not ds.looks_like_notice_url(
        "https://bip.nowydwormaz.pl/plik,5279,kwestionariusz-osobowy.pdf")
    assert not ds.looks_like_notice_url("https://bip.x.pl/pliki/ogloszenie.pdf")


def test_looks_like_notice_url_pusty():
    assert not ds.looks_like_notice_url("")


def test_slug_cms_bez_numeru():
    """CMS-y bez ID w adresie - wpis rozpoznawany po slugu na znanej domenie."""
    assert ds.looks_like_notice_url(
        "https://niepelnosprawni.gov.pl/ogloszenie-uzupelniajace-o-nabor")
    assert ds.looks_like_notice_url(
        "https://bip.powiatbytowski.pl/strony/11712.dhtml")
    assert ds.looks_like_notice_url(
        "https://bip.skoczow.pl/ogloszenie-o-naborze-kandydata-na-czlonka")


def test_nieznana_domena_bez_id_odrzucona():
    assert not ds.looks_like_notice_url(
        "https://jakaslosowa-strona.pl/ogloszenie-o-naborze-do-rady")
