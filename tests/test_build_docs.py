# -*- coding: utf-8 -*-
"""Testy build_docs.py: generator kalendarza iCalendar (bez sieci)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")

from build_docs import _ics_escape, build_ics


def test_ics_escape_special_chars():
    assert _ics_escape("a,b;c\\d") == "a\\,b\\;c\\\\d"
    assert _ics_escape("linia1\nlinia2") == "linia1\\nlinia2"


def test_ics_structure_and_active_only():
    offers = [
        {"podmiot": "Spółka ABC", "termin_skladania_ofert": "2099-09-15",
         "url": "https://a.pl/1", "podsumowanie": "Nabór, czynny"},
        {"podmiot": "Archiwalna", "termin_skladania_ofert": "2020-01-01",
         "url": "https://a.pl/2", "podsumowanie": ""},
        {"podmiot": "Bez terminu", "termin_skladania_ofert": "",
         "url": "https://a.pl/3", "podsumowanie": ""},
    ]
    ics = build_ics(offers, today="2099-09-01")
    assert ics.startswith("BEGIN:VCALENDAR")
    assert ics.rstrip().endswith("END:VCALENDAR")
    # Tylko aktywna oferta (termin >= today) trafia do kalendarza
    assert ics.count("BEGIN:VEVENT") == 1
    assert "SUMMARY:Spółka ABC" in ics
    assert "DTSTART;VALUE=DATE:20990915" in ics
    # DTEND wyłączny = termin + 1 dzień
    assert "DTEND;VALUE=DATE:20990916" in ics
    assert "UID:" in ics and "@rn-dorking" in ics
    # Escapowanie przecinka w opisie
    assert "Nabór\\, czynny" in ics


def test_ics_uid_stable_across_builds():
    offers = [{"podmiot": "X", "termin_skladania_ofert": "2099-12-01",
               "url": "https://a.pl/x", "podsumowanie": ""}]
    ics1 = build_ics(offers, today="2099-01-01")
    ics2 = build_ics(offers, today="2099-02-02")
    uid1 = [l for l in ics1.split("\r\n") if l.startswith("UID:")][0]
    uid2 = [l for l in ics2.split("\r\n") if l.startswith("UID:")][0]
    assert uid1 == uid2  # stabilny UID = kalendarz aktualizuje, nie duplikuje


def test_ics_crlf_line_endings():
    ics = build_ics([], today="2099-01-01")
    assert "\r\n" in ics  # RFC 5545 wymaga CRLF