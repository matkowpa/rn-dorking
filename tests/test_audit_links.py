# -*- coding: utf-8 -*-
"""Testy audytu linków (tools/audit_links.py) - bez sieci."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import audit_links as al  # noqa: E402


def test_summarize_liczy_statusy():
    reports = [
        {"status": "ok"}, {"status": "ok"}, {"status": "menu"}, {"status": "dead"},
    ]
    assert al.summarize(reports) == {"ok": 2, "menu": 1, "dead": 1}


def test_classify_dead_gdy_brak_odpowiedzi(monkeypatch):
    monkeypatch.setattr(al.cf, "_fetch", lambda url: None)
    status, detail = al.classify("https://bip.x.pl/martwy")
    assert status == "dead"
    assert "nieudane" in detail


def test_classify_ok_gdy_tresc_w_html(monkeypatch):
    class Resp:
        text = ("<html><body>Oferty należy składać do dnia 15 listopada "
                "2026 r.</body></html>")
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = "utf-8"

    monkeypatch.setattr(al.cf, "_fetch", lambda url: Resp())
    status, detail = al.classify("https://bip.x.pl/ogloszenie")
    assert status == "ok"
    assert "HTML" in detail


def test_classify_menu_gdy_sama_nawigacja(monkeypatch):
    class Resp:
        text = ("<html><body>Rejestr zgłoszeń budowy Oferta inwestycyjna "
                "Wzory pełnomocnictw Stawki podatkowe Mapa serwisu</body></html>")
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = "utf-8"

    monkeypatch.setattr(al.cf, "_fetch", lambda url: Resp())
    status, detail = al.classify("https://bip.x.pl/")
    assert status == "menu"


def test_classify_ok_gdy_termin_w_pdf(monkeypatch):
    """Strona-menu, ale załącznik PDF ma termin - to realne ogłoszenie."""
    class Root:
        text = ('<html><body>Mapa serwisu '
                '<a href="/pliki/ogloszenie.pdf">Ogłoszenie o naborze</a>'
                '</body></html>')
        headers = {"Content-Type": "text/html"}
        encoding = None
        apparent_encoding = "utf-8"

    class Pdf:
        content = b"%PDF-1.4"
        headers = {"Content-Type": "application/pdf"}
        encoding = None
        apparent_encoding = "utf-8"

    monkeypatch.setattr(al.cf, "_fetch",
                        lambda url: Pdf() if url.endswith(".pdf") else Root())
    monkeypatch.setattr(al.cf, "_extract_pdf_text",
                        lambda content: "Oferty składać do 15 listopada 2026 r.")
    status, detail = al.classify("https://bip.x.pl/ogloszenia")
    assert status == "ok"
    assert "2026-11-15" in detail


def test_audit_limit(monkeypatch):
    monkeypatch.setattr(al, "classify", lambda url: ("ok", "test"))
    offers = [{"url": f"https://x.pl/{i}", "podmiot": f"P{i}"} for i in range(5)]
    reports = al.audit(offers, limit=2)
    assert len(reports) == 2
    assert reports[0]["status"] == "ok"


def test_audit_nie_modyfikuje_wejscia(monkeypatch):
    monkeypatch.setattr(al, "classify", lambda url: ("dead", "test"))
    offers = [{"url": "https://x.pl/1", "podmiot": "P"}]
    al.audit(offers)
    assert "link_status" not in offers[0]
