# -*- coding: utf-8 -*-
"""Testy storage.py: normalizacja URL, deduplikacja, trwałość, plik dnia."""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import pytest

import storage as storage_mod
from storage import Storage, _normalize_url, _url_hash


@pytest.fixture
def storage(tmp_path, monkeypatch):
    """Storage działający w katalogu tymczasowym (izolacja od repo)."""
    monkeypatch.chdir(tmp_path)
    return Storage(offers_path="oferty.json", state_path="stan.json")


OFFER = {
    "podmiot": "Spółka Testowa Łąć Węgiel",
    "url": "https://Przyklad.pl/nabor/?utm_source=test",
    "termin_skladania_ofert": "2026-09-15",
}


def test_normalize_url_lowercases_host():
    assert _normalize_url("HTTPS://Przykład.PL/Ścieżka") == "https://przykład.pl/Ścieżka"


def test_normalize_url_strips_utm_and_fragment():
    url = "https://example.pl/a?utm_source=x&utm_medium=y&id=1#top"
    assert _normalize_url(url) == "https://example.pl/a?id=1"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.pl/a/") == "https://example.pl/a"


def test_is_new_and_dedup(storage):
    assert storage.is_new(OFFER["url"]) is True
    assert storage.merge_offers([OFFER]) == 1
    assert storage.merge_offers([OFFER]) == 0  # drugi raz = duplikat


def test_dedup_across_url_variants(storage):
    storage.merge_offers([OFFER])
    # Ten sam URL: inne wielkości, utm_, fragment, trailing slash -> duplikat
    assert storage.is_new("https://przyklad.pl/nabor/?utm_source=other#frag") is False


def test_persistence_utf8_and_sort(storage):
    storage.merge_offers([
        {**OFFER, "termin_skladania_ofert": "2026-09-01"},
        {**OFFER, "url": "https://example.pl/b", "termin_skladania_ofert": "2026-09-20"},
        {**OFFER, "url": "https://example.pl/c", "termin_skladania_ofert": ""},
    ])
    storage.save()
    with open("oferty.json", encoding="utf-8") as f:
        saved = json.load(f)
    # polskie znaki surowo (bez \uXXXX)
    assert "Łąć" in json.dumps(saved, ensure_ascii=False)
    # sortowanie malejąco po terminie, "" na końcu
    terms = [o["termin_skladania_ofert"] for o in saved]
    assert terms == ["2026-09-20", "2026-09-01", ""]


def test_reload_keeps_seen_urls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s1 = Storage(offers_path="o.json", state_path="s.json")
    s1.merge_offers([OFFER])
    s1.save()
    s2 = Storage(offers_path="o.json", state_path="s.json")
    assert s2.is_new(OFFER["url"]) is False


def test_save_daily_merges_same_day(storage):
    storage.merge_offers([{**OFFER, "znaleziono_dnia": "2026-08-29"}])
    stats = {"raw_results": 1, "offers_added": 1}
    p1 = storage.save_daily(stats, run_date="2026-08-29")
    assert storage._load_json(p1)["offers"]
    # Drugi run tego samego dnia z nową ofertą - nic nie ginie
    storage.merge_offers([{**OFFER, "url": "https://example.pl/2",
                           "znaleziono_dnia": "2026-08-29"}])
    p2 = storage.save_daily(stats, run_date="2026-08-29")
    assert p1 == p2
    day = storage._load_json(p2)
    assert len(day["offers"]) == 2
    assert day["stats"] == stats


def test_url_hash_stable():
    assert _url_hash("https://a.pl/x") == _url_hash("https://a.pl/x/")
