# -*- coding: utf-8 -*-
"""Testy direct_sources: linki-kandydaci i okno JST (bez wywołań sieciowych)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from bs4 import BeautifulSoup

from direct_sources import _candidate_links, jst_daily_slice


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
    # Okno przechodzące przez koniec listy (start + window > len)
    reg = list(range(5))
    day = __import__("datetime").datetime.now().timetuple().tm_yday
    window = 4
    start = (day * window) % len(reg)
    expected = reg[start:] + reg[:window - (len(reg) - start)] \
        if start + window > len(reg) else reg[start:start + window]
    assert jst_daily_slice(reg, window=window) == expected


def test_jst_daily_slice_edge_cases():
    reg = list(range(3))
    # Okno większe niż rejestr -> cały rejestr
    assert jst_daily_slice(reg, window=100) == reg
    # Pusty rejestr / window <= 0 -> []
    assert jst_daily_slice([], window=10) == []
    assert jst_daily_slice(reg, window=0) == []