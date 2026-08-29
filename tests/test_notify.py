# -*- coding: utf-8 -*-
"""Testy notify.py: budowa digestu i formatowanie dat (bez wysyłania wiadomości)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from notify import _fmt_date, build_digest


def test_fmt_date():
    assert _fmt_date("2026-09-15") == "15.09.2026"
    assert _fmt_date("") == ""


def test_build_digest_contains_offer():
    offers = [{
        "podmiot": "TORPOL", "miejscowosc": "Poznań",
        "termin_skladania_ofert": "2026-09-04", "url": "https://example.pl/t",
    }]
    text, html = build_digest(offers, [], "2026-08-29")
    assert "TORPOL" in text
    assert "Poznań" in text
    assert "2026-09-04" in text
    assert "https://example.pl/t" in html
    assert "1 nowe nabory" in text


def test_build_digest_reminders_section():
    from datetime import date, timedelta
    import re
    term = (date.today() + timedelta(days=5)).isoformat()
    offers, reminders = [], [{
        "podmiot": "Gmina X", "termin_skladania_ofert": term, "url": "https://example.pl/r",
    }]
    text, html = build_digest(offers, reminders, date.today().isoformat())
    assert "Przypomnienia" in text
    assert "Gmina X" in text
    # Liczba dni zależy od pory dnia (datetime.today() z czasem) - sprawdzamy wzorzec
    assert re.search(r"za \d+ dni", text)
    assert "Przypomnienia" in html


def test_build_digest_unknown_term_placeholder():
    text, _ = build_digest(
        [{"podmiot": "ABC", "termin_skladania_ofert": "", "url": "https://e.pl"}],
        [], "2026-08-29")
    assert "termin: nieznany" in text
